"""
test_yahoo_tw.py — 測試 YahooTwCrawler

執行方式：
    cd ~/Desktop/stock_sentiment
    python3 test_yahoo_tw.py

測試項目：
    1. RSS 能否成功抓取
    2. 每筆資料的必要欄位是否完整
    3. pubDate 能否轉換為 datetime
    4. 股票代號擷取邏輯是否正常
    5. 寫入 SQLite 並驗證，最後清除測試 DB
"""

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent))

from crawlers.yahoo_tw import YahooTwCrawler
from models.db import create_tables, fetch_articles, get_connection, insert_articles


def sep(label: str = ""):
    print(("── " + label + " ").ljust(50, "─") if label else "─" * 50)


def main():
    sep("YahooTwCrawler 測試開始")

    # ── 1. 爬取 ────────────────────────────────────────
    crawler = YahooTwCrawler()
    articles = crawler.run()

    if not articles:
        print("[FAIL] 沒有爬到任何文章，請確認網路連線或 RSS 是否可用")
        return

    print(f"\n共爬到 {len(articles)} 篇文章\n")

    # ── 2. 逐筆印出關鍵欄位（最多顯示 5 篇）────────────
    for i, a in enumerate(articles[:5], 1):
        print(f"[{i}] {a.title}")
        print(f"     來源       : {a.source}")
        print(f"     URL        : {a.url}")
        print(f"     發布時間   : {a.published_at}")
        print(f"     股票代號   : {a.stock_codes}")
        print(f"     content 前 80 字: {(a.content or '')[:80]}")
        print(f"     content_hash   : {a.content_hash}")
        print()

    # ── 3. 欄位驗證 ────────────────────────────────────
    sep("欄位驗證")
    all_pass = True
    for a in articles:
        checks = {
            "title 非空":        bool(a.title),
            "url 非空":          bool(a.url),
            "published_at 有效": a.published_at is not None,
            "content_hash 非空": bool(a.content_hash),
            "source == yahoo_tw": a.source == "yahoo_tw",
        }
        for name, ok in checks.items():
            if not ok:
                print(f"  [FAIL] {a.url[:60]} — {name}")
                all_pass = False

    if all_pass:
        print("  所有文章欄位驗證通過")

    # ── 4. 股票代號擷取測試 ────────────────────────────
    sep("股票代號擷取")
    test_cases = [
        ("台積電(2330)創新高", ["2330"]),
        ("聯發科 2454-TW 法說會", ["2454"]),
        ("2023年台股展望與2330走勢", ["2330"]),   # 2023 應被過濾
        ("美股重挫，科技股全面下跌", []),           # 無股票代號
    ]
    extract = YahooTwCrawler._extract_stock_codes
    extract_pass = True
    for text, expected in test_cases:
        result = extract(text)
        ok = set(result) == set(expected)
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {text!r} → {result} (expected {expected})")
        if not ok:
            extract_pass = False

    # ── 5. SQLite 寫入驗證 ─────────────────────────────
    sep("SQLite 寫入驗證")
    test_db = Path(__file__).parent / "data" / "test_yahoo.db"
    conn = get_connection(test_db)
    create_tables(conn)

    n = insert_articles(conn, articles)
    print(f"  寫入 {n} 筆")

    rows = fetch_articles(conn, source="yahoo_tw", limit=5)
    print(f"  查詢回 {len(rows)} 筆")

    first = rows[0] if rows else None
    db_checks = {
        "source == yahoo_tw": first and first["source"] == "yahoo_tw",
        "title 非空":         first and bool(first["title"]),
        "url 非空":           first and bool(first["url"]),
        "published_at 非空":  first and bool(first["published_at"]),
        "content_hash 非空":  first and bool(first["content_hash"]),
    }
    db_pass = True
    for name, ok in db_checks.items():
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}")
        if not ok:
            db_pass = False

    conn.close()
    test_db.unlink(missing_ok=True)
    print("  測試 DB 已清除")

    # ── 總結 ──────────────────────────────────────────
    sep()
    overall = all_pass and extract_pass and db_pass
    print("測試結果：", "全部通過 ✓" if overall else "有項目失敗，請確認上方輸出")
    sep()


if __name__ == "__main__":
    main()
