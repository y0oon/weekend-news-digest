"""
generate_digest.py — 収集ニュースを Gemini で「週末ダイジェスト記事」に変換

fetch_news.fetch_all() の出力を素材として Gemini に渡し、
WordPress カスタムHTMLブロックにそのまま貼れる本文HTML（スコープ済みCSS込み）を生成する。

設計方針:
- WordPress 7.0 仕様: <html>/<head>/<body> を出さず、単一ルート <div id="rdt-article"> に <style> を内包
- CLAUDE.md のデザインシステム（シアン系・LINA/YUN吹き出し）に準拠
- Gemini にはニュースの「要約・再構成」だけさせ、出典URLは必ず保持させる
- ハルシネーション防止: 「与えたニュース以外の事実を作らない」を明示
"""

import datetime
import os

from google import genai
from dotenv import load_dotenv

from fetch_news import fetch_all

MODEL = "gemini-flash-latest"

# 編集後記で使うちびキャラ画像（公式URL・名前は画像内に焼き込み済み）
# 配置ルール（プロジェクト確定）: YUN=先輩・右 / LINA=後輩・左
CHIBI_YUN = "https://www.raditech-fire.com/wp-content/uploads/2026/03/ちびYUN4（名前付き）.jpg"  # 楽顔
CHIBI_LINA = "https://www.raditech-fire.com/wp-content/uploads/2026/03/ちびLINA4（名前付き）.jpg"  # 楽顔

# 記事に採用する最大件数（多すぎると冗長・無料枠も食う）
# 日本重点なので国内を厚めに確保し、海外は最新トピックを少数だけ添える
MAX_DOMESTIC = 9
MAX_OVERSEAS = 3


def _split_by_region(items):
    """items を国内/海外に分け、それぞれ件数上限で切る（新しい順は呼び出し元で担保）。"""
    domestic = [it for it in items if it.get("region") != "overseas"][:MAX_DOMESTIC]
    overseas = [it for it in items if it.get("region") == "overseas"][:MAX_OVERSEAS]
    return domestic, overseas


def _format_items(items, start=1):
    lines = []
    for i, it in enumerate(items, start):
        lines.append(
            f"[{i}] ({it['category']} / {it['source']} / {it['published']})\n"
            f"  タイトル: {it['title']}\n"
            f"  概要: {it['summary']}\n"
            f"  出典URL: {it['url']}"
        )
    return "\n\n".join(lines) if lines else "（該当なし）"


def build_prompt(items, week_label):
    domestic, overseas = _split_by_region(items)
    domestic_block = _format_items(domestic, start=1)
    overseas_block = _format_items(overseas, start=len(domestic) + 1)
    return f"""あなたは放射線技師向けメディア「RadiTech」の編集者です。
以下の「今週のニュース素材」だけを使って、週末に読みたくなる軽めの
「今週の放射線技師ニュース・週末ダイジェスト」記事の本文HTMLを作成してください。

# 最重要ルール（厳守）
- 与えられたニュース素材に書かれていない事実・数値・固有名詞を絶対に創作しないこと（ハルシネーション禁止）。
- 各トピックには必ず出典リンクを `<a href="出典URL" target="_blank" rel="noopener">出典: 媒体名</a>` の形で付けること。
- 放射線技師の実務にどう関係するか、という視点で短くコメントを添えること（専門家として、ただし堅すぎず）。
- 一人称は「私」。「僕」は禁止。
- 全体で読了2〜3分程度の軽い分量。週末のリラックスした読み物トーン。

# 構成方針（重要・日本のニュースが主役）
- 記事の主役は「国内ニュース」。本文の大半を国内ニュースに充て、ピックアップ（最重要1本）も原則は国内から選ぶ。
- 海外ニュースは記事末尾に「🌍 海外の最新トピック」という独立した小セクションを設け、1〜2本だけコンパクトに紹介する（多用しない）。海外素材が無ければこのセクションは省略してよい。
- 海外トピックは英語素材なので、日本語で要約・翻訳して紹介すること（固有名詞・数値は素材どおり）。

# デザイン方針（モダンマガジン風・厳守）
全体を「洗練されたWebマガジンの紙面」として組む。情報を縦に積むだけのブログにしない。
- **マストヘッド（題字）**: 記事最上部に新聞の題字のような帯。左に「RadiTech 週刊」のロゴ風テキスト、
  右に発行日と「{week_label} 号」。上下に細い罫線（border-top/bottom）を引き、紙面の見出し帯らしくする。
- **トップ特集（リード記事）**: ピックアップ1本を大きく扱う。大きな見出し（28〜34px相当）＋カテゴリの
  小さなラベル（eyebrow）＋本文＋「放射線技師の視点」コメント。左に太い縦罫(border-left)でアクセント。
  ここに将来の画像枠として `<div class="article-figure">（写真スペース）</div>` を1つ用意してよい（任意）。
- **カードグリッド（国内のそのほかの動き）**: 残りの国内ニュースを2カラムのカード(grid)で並べる。
  各カード＝カテゴリラベル＋見出し＋短い要約＋出典リンク。カードは白背景・薄い罫線・角丸・控えめな影。
- **海外コーナー**: 末尾に「🌍 海外の最新トピック」。色味を少し変えた帯（ダーク背景など）で区切り、1〜2本。
- **タイポグラフィ**: 見出しは明朝系(serif: "Times New Roman", "游明朝", "Yu Mincho", serif)で新聞らしさ、
  本文はゴシック系(sans-serif)。リード記事の本文先頭にドロップキャップ(::first-letter を大きく)を入れてよい。
- 土台は「上品・知的・余白多め」。色を使いすぎず、罫線と余白で構造を見せる。

# 遊び心の演出（重要・固い新聞にしない）
紙面の骨格は新聞だが、所々に手作り感・ポップさを散らして「読んでいて楽しい号外」にする。
- **号外スタンプ風バッジ**: マストヘッド付近に「号外」「今週号」等の丸い/四角いスタンプ風ラベルを少し傾けて(transform: rotate)貼る。
- **付箋・マスキングテープ風**: ピックアップやカードの角に、付箋やマステを貼ったような小さな装飾(疑似要素や小boxを傾けて配置)を入れてよい。
- **手書き風マーカー**: 重要語に蛍光マーカー風の下線(linear-gradient(transparent 60%, #fde68a 60%)等)。色は黄・シアン・ピンクを使い分け。
- **キャラのひとことシール**: ピックアップ記事の脇に、LINAかYUNの「ふきだしシール」(小さな丸い吹き出し)で一言ツッコミを入れてよい。
- **絵文字アイコン**: カテゴリラベルに🏥💉🔬📋🌍☢️等の絵文字を添えて視認性とポップさを上げる。
- やりすぎ注意: 装飾は"アクセント"。本文の可読性は最優先。1セクションに装飾は1〜2個まで。

# 編集後記（ちびキャラ画像つき・必ずこの形式で出力）
記事の最後に「☕ 編集後記」セクションを設け、LINAとYUNのちびキャラ画像つき吹き出しで今週を1〜2往復で締める。
画像は必ず下記URLをそのまま使う(URLは一字一句変えない・日本語ファイル名のまま)。配置はYUN=右・LINA=左。
吹き出しは次の構造を使うこと（balloon-icon内は<img>のみ。名前は画像に焼き込み済みなのでテキスト名は不要）:

<div class="postscript">
  <h2>☕ 編集後記</h2>
  <div class="balloon-box balloon-left">
    <div class="balloon-icon"><img src="{CHIBI_LINA}" alt="LINA" /></div>
    <div class="balloon-serif"><div class="balloon-content"><p>（LINAの後輩らしい一言）</p></div></div>
  </div>
  <div class="balloon-box balloon-right">
    <div class="balloon-icon"><img src="{CHIBI_YUN}" alt="YUN" /></div>
    <div class="balloon-serif"><div class="balloon-content"><p>（YUNの先輩らしいまとめ）</p></div></div>
  </div>
</div>

吹き出しのCSSも #rdt-article スコープで必ず定義すること:
- .balloon-icon img は width/height 64px・border-radius 20px・background white・padding 4px・box-shadow・border 1px solid #e2e8f0・object-fit cover。
- balloon-left は画像左・本文右、balloon-right は画像右・本文左(flex-direction: row-reverse)。
- 吹き出し本文は角丸20px・薄い背景色(LINA側=#f0f9ff/水色, YUN側=#fffbeb/アンバー)・小さなしっぽ(::before)。
- モバイル(640px以下)で画像を52pxに縮小。

# WordPress 出力仕様（厳守）
- 出力は本文HTMLのみ。説明文やコードフェンス(```)は一切付けない。
- <html>/<head>/<body> タグは使わない。単一のルート要素 `<div id="rdt-article">` で全体を包む。
- <style> タグはルートdivの直下に置く。全セレクタを `#rdt-article ` で始め `!important` を付ける。
- 配色はシアン系をアクセントに: プライマリ #0891b2 / ダーク #0c4a6e / アンバー #f59e0b。
  紙面のベースは白〜オフホワイト(#fafaf9等)＋濃いインク色のテキスト(#1c1917)＋罫線(#d6d3d1)。
- 各トピックには必ず出典リンク `<a href="出典URL" target="_blank" rel="noopener">出典: 媒体名</a>` を付ける。
- **レスポンシブ必須**: #rdt-article に overflow-x:hidden と box-sizing:border-box。
  カードグリッドや多段組みは @media (max-width:768px) で必ず1カラムに畳む。grid子要素には min-width:0 を付ける。

# 今週のニュース素材【国内】（主役・本文の中心にする）
{domestic_block}

# 今週のニュース素材【海外】（末尾の小セクションで1〜2本だけ・日本語に要約）
{overseas_block}

それでは本文HTMLを出力してください（コードフェンス無し・HTMLのみ）:"""


def generate(items=None, save=True):
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("Error: GEMINI_API_KEY が .env に見つかりません")

    if items is None:
        items = fetch_all()

    if not items:
        raise SystemExit("ニュースが0件のため記事を生成できません（フィード障害の可能性）")

    now = datetime.datetime.now()
    week_label = now.strftime("%Y年%-m月第") + str((now.day - 1) // 7 + 1) + "週"

    domestic, overseas = _split_by_region(items)
    used = domestic + overseas

    client = genai.Client(api_key=api_key)
    prompt = build_prompt(items, week_label)

    print(f"[generate_digest] Gemini ({MODEL}) で記事生成中... 採用 国内{len(domestic)}件 + 海外{len(overseas)}件")
    response = client.models.generate_content(model=MODEL, contents=prompt)
    html = (response.text or "").strip()

    # 念のためコードフェンスが付いていたら剥がす
    if html.startswith("```"):
        html = html.split("\n", 1)[1] if "\n" in html else html
        html = html.rsplit("```", 1)[0].strip()

    if save:
        out_dir = os.path.join(os.path.dirname(__file__), "generated")
        os.makedirs(out_dir, exist_ok=True)
        fname = os.path.join(out_dir, f"digest_{now.strftime('%Y%m%d')}.html")
        with open(fname, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"[generate_digest] 保存: {fname}")

    return {"html": html, "week_label": week_label, "items": used}


if __name__ == "__main__":
    result = generate()
    print("\n--- 生成HTML（先頭500字） ---")
    print(result["html"][:500])
