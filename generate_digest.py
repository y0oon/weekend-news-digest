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

# WordPress 出力仕様（厳守）
- 出力は本文HTMLのみ。説明文やコードフェンス(```)は一切付けない。
- <html>/<head>/<body> タグは使わない。単一のルート要素 `<div id="rdt-article">` で全体を包む。
- <style> タグはルートdivの直下に置く。全セレクタを `#rdt-article ` で始め `!important` を付ける。
- 配色はシアン系: プライマリ #0891b2 / ダーク #0c4a6e / アンバー #f59e0b。
- 見出し構成例:
  - ヒーロー（タイトル「今週の放射線技師ニュース」＋{week_label}＋一言リード）
  - 「今週のピックアップ」（最重要1本＝原則国内、少し厚めに）
  - 「国内のそのほかの動き」（残りの国内ニュースをコンパクトに、各出典リンク付き）
  - 「🌍 海外の最新トピック」（海外1〜2本。素材があれば）
  - LINA（後輩）と YUN（先輩）の短い吹き出し会話で今週を締める1往復（任意・1〜2往復まで）
- 吹き出しを使う場合のみ、画像は使わず名前ラベル＋テキストの簡易版でよい（例: <div class="balloon yun"><b>YUN</b> …</div>）。
- レスポンシブで崩れないこと（overflow-x:hidden、box-sizing:border-box を #rdt-article に付与）。

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
