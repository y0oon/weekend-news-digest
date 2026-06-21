# 週末ニュースダイジェスト（自動生成）

**「今週の放射線技師ニュース・週末ダイジェスト」**を
Gemini無料APIで自動生成し、WordPressに**下書き**として保存する仕組み。

放射線・医療・診療報酬系のRSSを収集 → Geminiで要約・記事化 → WP下書き投稿、までを
GitHub Actionsの週次cron（毎週土曜 朝）で自動実行する。

## パイプライン

```
fetch_news.py   RSS収集（直近8日・出典URL保持・リトライ付き）
      ↓
generate_digest.py   Geminiで週末ダイジェスト記事HTMLを生成（スコープ済みCSS・LINA/YUN）
      ↓
post_draft.py   WP REST APIに status=draft で投稿（公開は手動）
      ↑
run.py   上記を一括実行するオーケストレーター（cronのエントリポイント）
```

## ローカル実行

```bash
pip install -r requirements.txt

cp .env.example .env        # ← .env を作って値を埋める（.env はコミットされない）

python3 run.py --dry-run   # ① まず収集だけ確認（ニュースが取れるか）
python3 run.py --no-post   # ② 記事生成までやって generated/ に保存（投稿しない）
python3 run.py             # ③ 収集→生成→WP下書き投稿まで一気通貫
```

認証は **リポジトリ直下の `.env`**（`.env.example` をコピーして作成）から読む:
- `GEMINI_API_KEY` … Gemini API（無料枠）
- `WP_USER` / `WP_APP_PASS` … WordPress Application Password（投稿作成用）

## 自動化（GitHub Actions）

`.github/workflows/weekend-news-digest.yml`

- **スケジュール**: 毎週土曜 08:00 JST（金 23:00 UTC）
- **手動実行**: Actionsタブから `workflow_dispatch`（`no_post=true` で投稿せず生成のみ）
- **必要なSecrets**（リポジトリ Settings → Secrets and variables → Actions）:
  - `GEMINI_API_KEY`
  - `WP_USER`
  - `WP_APP_PASS`

### 公開フロー

自動投稿は必ず **下書き（draft）**。実行後にWP管理画面の下書きを開き、
内容（特に出典リンク・誤情報の有無）を確認してから手動で公開する。
慣れてきたら `post_draft.py` の `status` を `"publish"` にすれば全自動公開も可能。

## ニュースソースの調整

`fetch_news.py` の `FEEDS` リストを編集する。フィードが落ちても個別skipされるだけなので、
気になる媒体を随時追加・削除してよい。`LOOKBACK_DAYS`（対象期間）や
`MAX_PER_FEED`（1媒体あたり件数）も上部定数で調整可能。

## 将来案（ストック）

当初の検討で出た別コンテンツ案（実装は保留・必要になったらここから着手）:
- 放射線の歴史・偉人エピソード（日付ローテで無メンテ）
- 放射線技師の雑学・トリビア
- 今週の論文ピック（論文ピラー連動）
- LINAの週末QA予報（Open-Meteo実測連動）
