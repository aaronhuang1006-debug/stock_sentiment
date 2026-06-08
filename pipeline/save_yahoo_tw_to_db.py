"""
save_yahoo_tw_to_db.py — 將 Yahoo 奇摩股市新聞存入 SQLite

執行方式：
    cd ~/Desktop/stock_sentiment
    python3 pipeline/save_yahoo_tw_to_db.py
"""

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent.parent))

from crawlers.yahoo_tw import YahooTwCrawler
from models.db import create_tables, get_connection, insert_article

DB_PATH = Path(__file__).parent.parent / "data" / "news.db"


def main():
    conn = get_connection(DB_PATH)
    create_tables(conn)

    crawler = YahooTwCrawler()
    articles = crawler.run()
    total = len(articles)

    inserted = skipped = 0
    for article in articles:
        if insert_article(conn, article):
            inserted += 1
        else:
            skipped += 1

    conn.close()

    print()
    print("── 執行結果 ──────────────────────────")
    print(f"  抓到  : {total} 篇")
    print(f"  新增  : {inserted} 篇")
    print(f"  跳過  : {skipped} 篇（重複）")
    print(f"  DB 位置: {DB_PATH}")
    print("──────────────────────────────────────")


if __name__ == "__main__":
    main()
