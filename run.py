"""
run.py — 週末ニュースダイジェスト オーケストレーター

fetch（RSS収集）→ generate（Gemini記事化）→ post（WP下書き保存）を一括実行。
GitHub Actions の週次cronから呼ばれるエントリポイント。

使い方:
  python3 run.py            # 収集→生成→下書き投稿まで一気通貫
  python3 run.py --no-post  # 投稿せず生成HTMLの保存だけ（ローカル確認用）
  python3 run.py --dry-run  # 収集だけ（ニュースが取れているか確認）
"""

import sys

from fetch_news import fetch_all
from generate_digest import generate
from post_draft import post_draft


def main():
    no_post = "--no-post" in sys.argv
    dry_run = "--dry-run" in sys.argv

    print("=" * 50)
    print("週末ニュースダイジェスト 生成パイプライン")
    print("=" * 50)

    items = fetch_all()
    if not items:
        print("⚠ ニュースが0件です。フィード障害の可能性。中止します。")
        sys.exit(1)

    if dry_run:
        print("\n[dry-run] 収集のみで終了。上位5件:")
        for it in items[:5]:
            print(f"  - [{it['category']}] {it['title']} ({it['source']})")
        return

    result = generate(items=items, save=True)

    if no_post:
        print("\n[--no-post] 生成HTMLを保存しました。投稿はスキップ。")
        return

    post_draft(result["html"], result["week_label"], result["items"])
    print("\n✅ 完了。WP管理画面の下書きを確認 → 問題なければ公開してください。")


if __name__ == "__main__":
    main()
