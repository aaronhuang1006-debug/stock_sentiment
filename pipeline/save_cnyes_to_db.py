"""
save_cnyes_to_db.py — 將鉅亨網新聞存入 SQLite

流程：CnyesCrawler.run() → insert_articles() → 印出統計結果

執行方式：
    cd ~/Desktop/stock_sentiment
    python3 pipeline/save_cnyes_to_db.py
"""

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent.parent))

from crawlers.cnyes import CnyesCrawler
from models.db import create_tables, get_connection, insert_article

DB_PATH = Path(__file__).parent.parent / "data" / "news.db"


def main():
    # 建立資料庫連線（data/ 資料夾不存在時自動建立）
    conn = get_connection(DB_PATH)
    create_tables(conn)

    # 爬取
    crawler = CnyesCrawler(limit=30)
    articles = crawler.run()
    total = len(articles)

    # 逐筆插入，統計新增 vs 跳過
    inserted = 0
    skipped = 0
    for article in articles:
        if insert_article(conn, article):
            inserted += 1
        else:
            skipped += 1

    conn.close()

    # 統計輸出
    print()
    print("── 執行結果 ──────────────────")
    print(f"  抓到  : {total} 篇")
    print(f"  新增  : {inserted} 篇")
    print(f"  跳過  : {skipped} 篇（重複）")
    print(f"  DB 位置: {DB_PATH}")
    print("─────────────────────────────")


if __name__ == "__main__":
    main()
