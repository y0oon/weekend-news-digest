"""
fetch_news.py — 放射線技師向け「今週のニュース」収集モジュール

放射線・医療・診療報酬系の RSS フィードを取得し、直近 N 日以内の記事だけを
抽出して dict のリストで返す。Gemini に渡す素材になる。

設計方針:
- ネットワーク呼び出しには max_attempts と指数バックオフを設定（CLAUDE.md ポリシー）
- 1フィードが落ちても全体は止めない（個別 try/except）
- 出典 URL を必ず保持 → 記事で出典明示できる
"""

import datetime
import ssl
import time
import urllib.request

import certifi
import feedparser

# certifi の CA バンドルで TLS 検証する handler。
# python.org 版 Python(macOS) はシステム証明書ストアを見ないため、これで検証を通す。
# 検証は無効化していない（正規CAバンドルを使うだけ）。CI(Ubuntu)でもそのまま動く。
_SSL_CTX = ssl.create_default_context(cafile=certifi.where())
_HTTPS_HANDLER = urllib.request.HTTPSHandler(context=_SSL_CTX)

# 直近何日分を「今週」とみなすか
LOOKBACK_DAYS = 8

# 1フィードあたり最大何件まで拾うか（量産しすぎ防止）
MAX_PER_FEED = 8

# ネットワークリトライ設定
MAX_ATTEMPTS = 3
BACKOFF_BASE = 2  # 秒（指数バックオフ: 2, 4, 8...）

# フィード取得時の User-Agent（無いと 403 で弾く媒体がある）
USER_AGENT = "Mozilla/5.0 (compatible; RadiTechBot/1.0; +https://www.raditech-fire.com)"

# ──────────────────────────────────────────────
# RSS ソース一覧（2026-06 時点で取得成功を確認済みのものだけ）
#   放射線技師の関心領域: 医療行政・放射線部門経営・医学物理・放射線治療・医療研究
#   ※ フィードが落ちた/廃止された場合は個別 skip されるだけなので随時追加削除可
#   ※ 新規追加時は probe（README参照）で entries>0 を確認してから入れること
# ──────────────────────────────────────────────
FEEDS = [
    # ── 日本語（重点）── region="domestic"
    {"name": "厚生労働省 新着", "url": "https://www.mhlw.go.jp/stf/news.rdf",
     "category": "医療行政", "region": "domestic"},
    {"name": "GemMed (医療政策・診療報酬)", "url": "https://gemmed.ghc-j.com/?feed=rss2",
     "category": "医療政策・診療報酬", "region": "domestic"},
    {"name": "QLifePro 医療ニュース", "url": "https://www.qlifepro.com/feed",
     "category": "医療研究", "region": "domestic"},
    {"name": "薬事日報", "url": "https://www.yakuji.co.jp/feed",
     "category": "医療制度・薬事", "region": "domestic"},
    {"name": "日本核医学会", "url": "http://www.jsnm.org/feed",
     "category": "核医学・学会", "region": "domestic"},
    # ── 海外（最新トピックを少数）── region="overseas"
    {"name": "ScienceDaily 画像診断", "url": "https://www.sciencedaily.com/rss/health_medicine/medical_imaging.xml",
     "category": "画像診断研究(海外)", "region": "overseas"},
    {"name": "Radiology Business", "url": "https://radiologybusiness.com/rss.xml",
     "category": "放射線部門・AI(海外)", "region": "overseas"},
]


def _parse_entry_date(entry):
    """エントリの公開日時を datetime で返す。取れなければ None。"""
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            try:
                return datetime.datetime.fromtimestamp(time.mktime(t))
            except (OverflowError, ValueError):
                continue
    return None


def _fetch_one(feed):
    """1フィードをリトライ付きで取得し、直近 LOOKBACK_DAYS のエントリを返す。"""
    cutoff = datetime.datetime.now() - datetime.timedelta(days=LOOKBACK_DAYS)
    last_err = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            parsed = feedparser.parse(
                feed["url"],
                handlers=[_HTTPS_HANDLER],
                request_headers={"User-Agent": USER_AGENT},
            )
            # bozo は「整形式でない」警告。エントリが取れていれば実用上問題ないので採用する。
            # エントリが0件のときだけ本当の取得失敗とみなしてリトライ。
            if not parsed.entries:
                raise RuntimeError(f"no entries (bozo={parsed.get('bozo_exception')})")

            items = []
            for entry in parsed.entries[: MAX_PER_FEED * 2]:
                dt = _parse_entry_date(entry)
                # 日付不明は採用しない（古い記事の混入を防ぐ）
                if dt is None or dt < cutoff:
                    continue
                title = (entry.get("title") or "").strip()
                link = (entry.get("link") or "").strip()
                summary = (entry.get("summary") or entry.get("description") or "").strip()
                if not title or not link:
                    continue
                items.append({
                    "source": feed["name"],
                    "category": feed["category"],
                    "region": feed.get("region", "domestic"),
                    "title": title,
                    "url": link,
                    "summary": summary[:600],  # 長すぎる本文は切る
                    "published": dt.strftime("%Y-%m-%d"),
                })
                if len(items) >= MAX_PER_FEED:
                    break
            return items

        except Exception as e:  # noqa: BLE001 — どの種類でもリトライ対象
            last_err = e
            if attempt < MAX_ATTEMPTS:
                wait = BACKOFF_BASE ** attempt
                print(f"  [retry {attempt}/{MAX_ATTEMPTS}] {feed['name']}: {e} → {wait}s 待機")
                time.sleep(wait)

    print(f"  [skip] {feed['name']} 取得失敗: {last_err}")
    return []


def fetch_all():
    """全フィードを取得し、新しい順にソートした記事リストを返す。"""
    print(f"[fetch_news] {len(FEEDS)} フィードを取得中（直近{LOOKBACK_DAYS}日）...")
    all_items = []
    for feed in FEEDS:
        items = _fetch_one(feed)
        print(f"  - {feed['name']}: {len(items)}件")
        all_items.extend(items)

    # 新しい順
    all_items.sort(key=lambda x: x["published"], reverse=True)
    print(f"[fetch_news] 合計 {len(all_items)} 件取得")
    return all_items


if __name__ == "__main__":
    import json
    items = fetch_all()
    print(json.dumps(items, ensure_ascii=False, indent=2))
