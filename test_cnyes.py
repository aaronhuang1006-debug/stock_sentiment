"""
test_cnyes.py — 快速測試 CnyesCrawler

執行方式：
    cd ~/Desktop/stock_sentiment
    python3 test_cnyes.py

測試項目：
    1. 能否成功呼叫 API
    2. 每筆資料是否有 title / url / published_at / content
    3. content_hash 是否正確產生（去重用）
    4. 結果寫入 SQLite，確認存取正常
"""

import sys
from pathlib import Path

# 把專案根目錄加進 Python 路徑，這樣 import 才找得到 crawlers / models
sys.path.insert(0, str(Path(__file__).parent))

from crawlers.cnyes import CnyesCrawler
from models.db import create_tables, fetch_articles, get_connection, insert_articles


def main():
    print("=" * 50)
    print("CnyesCrawler 測試開始")
    print("=" * 50)

    # --- 1. 爬取 ---
    crawler = CnyesCrawler(limit=5)  # 只拿 5 筆，測試用
    articles = crawler.run()

    if not articles:
        print("[FAIL] 沒有爬到任何文章，請檢查網路或 API 是否正常")
        return

    print(f"\n共爬到 {len(articles)} 篇文章\n")

    # --- 2. 逐筆印出關鍵欄位 ---
    for i, a in enumerate(articles, 1):
        print(f"[{i}] {a.title}")
        print(f"     來源      : {a.source}")
        print(f"     URL       : {a.url}")
        print(f"     發布時間  : {a.published_at}")
        print(f"     股票代號  : {a.stock_codes}")
        print(f"     content 前80字 : {(a.content or '')[:80]}")
        print(f"     content_hash   : {a.content_hash}")
        print()

    # --- 3. 寫入 SQLite 並查詢回來驗證 ---
    test_db = Path(__file__).parent / "data" / "test.db"
    conn = get_connection(test_db)
    create_tables(conn)

    inserted = insert_articles(conn, articles)
    print(f"[DB] 寫入 {inserted} 筆（重複的會自動略過）")

    rows = fetch_articles(conn, source="cnyes", limit=5)
    print(f"[DB] 查詢回 {len(rows)} 筆\n")

    # 驗證第一筆的欄位完整性
    row = rows[0]
    checks = {
        "title 非空": bool(row["title"]),
        "url 非空": bool(row["url"]),
        "published_at 非空": bool(row["published_at"]),
        "content_hash 非空": bool(row["content_hash"]),
        "source == cnyes": row["source"] == "cnyes",
    }

    print("欄位驗證：")
    all_pass = True
    for name, result in checks.items():
        status = "PASS" if result else "FAIL"
        print(f"  [{status}] {name}")
        if not result:
            all_pass = False

    print()
    print("=" * 50)
    print("測試結果：", "全部通過" if all_pass else "有項目失敗，請確認上方輸出")
    print("=" * 50)

    conn.close()
    test_db.unlink(missing_ok=True)  # 清除測試用的暫存 DB


if __name__ == "__main__":
    main()
