"""
post_draft.py — 生成したダイジェスト記事を WordPress に「下書き」として投稿

WP REST API (/wp-json/wp/v2/posts) に status=draft で POST する。
公開はあなたが管理画面で内容を確認してから手動で行う（誤情報の自動公開を防ぐ）。

認証:
- WP_USER / WP_APP_PASS を .env から読む（Application Password）
- GitHub Actions では Secrets から環境変数で渡す（.env が無くても os.getenv で拾える）

設計方針:
- 本文は <!-- wp:html --> ... <!-- /wp:html --> でラップ（カスタムHTMLブロック）
- ネットワーク呼び出しは max_attempts + バックオフ
- ※ 固定ページ(page)ではなく投稿(post)。投稿は /posts エンドポイントで作成可
"""

import base64
import datetime
import json
import os
import ssl
import time
import urllib.request
import urllib.error

from dotenv import load_dotenv

WP_BASE = "https://www.raditech-fire.com"
ENDPOINT = f"{WP_BASE}/wp-json/wp/v2/posts"

MAX_ATTEMPTS = 3
BACKOFF_BASE = 2


def _open(req):
    """通常はTLS検証あり(create_default_context)で接続する。
    本番 www.raditech-fire.com は正規証明書なので検証を無効化しない。"""
    return urllib.request.urlopen(req, context=ssl.create_default_context(), timeout=30)


def post_draft(html, week_label, items=None):
    load_dotenv()
    user = os.getenv("WP_USER")
    app_pass = os.getenv("WP_APP_PASS")
    if not user or not app_pass:
        raise SystemExit("Error: WP_USER / WP_APP_PASS が見つかりません（.env または Secrets）")

    title = f"今週の放射線技師ニュース・週末ダイジェスト（{week_label}）"
    content = f"<!-- wp:html -->\n{html}\n<!-- /wp:html -->"

    payload = {
        "title": title,
        "content": content,
        "status": "draft",  # ★ 必ず下書き。公開は手動
        "excerpt": f"{week_label}の放射線技師・医療・診療報酬まわりの動きを週末向けにダイジェスト。",
    }
    data = json.dumps(payload).encode("utf-8")

    token = base64.b64encode(f"{user}:{app_pass}".encode()).decode()
    headers = {
        "Authorization": f"Basic {token}",
        "Content-Type": "application/json",
    }

    last_err = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            req = urllib.request.Request(ENDPOINT, data=data, headers=headers, method="POST")
            with _open(req) as res:
                body = json.loads(res.read().decode("utf-8"))
                post_id = body.get("id")
                edit_link = f"{WP_BASE}/wp-admin/post.php?post={post_id}&action=edit"
                print(f"[post_draft] 下書き作成成功 (ID={post_id})")
                print(f"[post_draft] 編集URL: {edit_link}")
                return {"id": post_id, "edit_link": edit_link}
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:300]}"
        except Exception as e:  # noqa: BLE001
            last_err = str(e)

        if attempt < MAX_ATTEMPTS:
            wait = BACKOFF_BASE ** attempt
            print(f"  [retry {attempt}/{MAX_ATTEMPTS}] {last_err} → {wait}s 待機")
            time.sleep(wait)

    raise SystemExit(f"[post_draft] 投稿失敗: {last_err}")


if __name__ == "__main__":
    # 直近に生成された digest_*.html を投稿（手動テスト用）
    gen_dir = os.path.join(os.path.dirname(__file__), "generated")
    files = sorted(
        [f for f in os.listdir(gen_dir) if f.startswith("digest_") and f.endswith(".html")]
    )
    if not files:
        raise SystemExit("generated/ に digest_*.html がありません。先に generate_digest.py を実行してください")
    latest = os.path.join(gen_dir, files[-1])
    with open(latest, encoding="utf-8") as f:
        html = f.read()
    now = datetime.datetime.now()
    week_label = now.strftime("%Y年%-m月第") + str((now.day - 1) // 7 + 1) + "週"
    print(f"[post_draft] 対象ファイル: {latest}")
    post_draft(html, week_label)
