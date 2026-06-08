"""
fetch_prices.py — 為已分析的新聞文章抓取股價並計算報酬率

使用方式：
    cd ~/Desktop/stock_sentiment
    python3 pipeline/fetch_prices.py           # 真實 yfinance 模式
    python3 pipeline/fetch_prices.py --mock    # mock 模式（離線展示用）
    python3 pipeline/fetch_prices.py --days 90 # 抓近 90 天文章（預設 30）

流程：
  1. 從 articles 讀取有 stock_codes 且已分析的文章（近 N 天）
  2. 對每個 (article, stock_code) 組合，抓取發布日前後的股價
  3. 計算 T+1 / T+3 / T+5 日報酬率
  4. 寫入 article_returns 表
"""

import argparse
import json
import random
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# ── 根目錄加入 PYTHONPATH ──────────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from models.db import DEFAULT_DB_PATH, get_connection
from models.price import compute_returns, fetch_tw_prices, get_validation_df

# ─────────────────────────────────────────────────────────────
# Mock 模式：產生假股價資料
# ─────────────────────────────────────────────────────────────

MOCK_STOCKS = [
    ("2330", 980.0),   # 台積電
    ("2317", 115.0),   # 鴻海
    ("2454", 890.0),   # 聯發科
    ("2882", 45.0),    # 國泰金
    ("2308", 125.0),   # 台達電
]


def _gen_mock_prices(stock_code: str, base_price: float, start: date, end: date) -> list:
    """
    產生模擬股價序列（隨機漲跌，接近真實日波動 ±2%）。
    回傳 list of (date_str, close)。
    """
    current = base_price
    result = []
    d = start
    while d <= end:
        if d.weekday() < 5:   # 跳過週末
            change = random.uniform(-0.02, 0.02)
            current = round(current * (1 + change), 2)
            result.append((d.isoformat(), current))
        d += timedelta(days=1)
    return result


def _insert_mock_prices(
    conn: sqlite3.Connection,
    stock_code: str,
    base_price: float,
    start: date,
    end: date,
) -> int:
    """把模擬股價寫入 stock_prices 表，回傳寫入筆數。"""
    prices = _gen_mock_prices(stock_code, base_price, start, end)
    inserted = 0
    now = datetime.now().isoformat()
    for date_str, close in prices:
        try:
            conn.execute(
                """INSERT OR IGNORE INTO stock_prices
                     (stock_code, date, close, source, fetched_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (stock_code, date_str, close, "mock", now),
            )
            if conn.execute("SELECT changes()").fetchone()[0]:
                inserted += 1
        except Exception:
            pass
    conn.commit()
    return inserted


def run_mock(conn: sqlite3.Connection, days: int = 30) -> dict:
    """
    Mock 模式：插入假股價 + 計算所有符合文章的報酬率。
    回傳執行摘要 dict。
    """
    print("[fetch_prices] 🎭  mock 模式")
    start = date.today() - timedelta(days=days + 10)
    end   = date.today() + timedelta(days=7)  # 多抓 7 天，保證 T+5 有資料
    price_rows = 0

    # 1. 對每個 mock 股票插入假股價
    for code, base in MOCK_STOCKS:
        n = _insert_mock_prices(conn, code, base, start, end)
        price_rows += n
        if n:
            print(f"  [mock] {code}：新增 {n} 筆模擬價格")

    # 2. 讀取文章並指派 stock_code（若文章 stock_codes 為空，輪流指派 mock 股票）
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        """SELECT id, stock_codes, published_at FROM articles
           WHERE sentiment IS NOT NULL
             AND published_at >= ?
           ORDER BY published_at DESC""",
        (cutoff,),
    ).fetchall()

    computed = 0
    mock_idx = 0
    for row in rows:
        codes = []
        try:
            codes = json.loads(row["stock_codes"] or "[]")
        except Exception:
            pass

        if not codes:
            codes = [MOCK_STOCKS[mock_idx % len(MOCK_STOCKS)][0]]
            mock_idx += 1

        pub_date = row["published_at"][:10]
        for code in codes[:2]:   # 每篇最多 2 支股票
            # 確保 mock 股票的股價存在
            if code not in [s[0] for s in MOCK_STOCKS]:
                # 用輪替方式補一個 mock stock
                code = MOCK_STOCKS[mock_idx % len(MOCK_STOCKS)][0]
                mock_idx += 1
            result = compute_returns(conn, row["id"], code, pub_date)
            if result.get("return_1d") is not None:
                computed += 1

    print(f"[fetch_prices] mock 完成：{price_rows} 筆價格，{computed} 筆報酬率")
    return {"price_rows": price_rows, "computed": computed, "mode": "mock"}


# ─────────────────────────────────────────────────────────────
# 真實模式：yfinance
# ─────────────────────────────────────────────────────────────

def run_real(conn: sqlite3.Connection, days: int = 30) -> dict:
    """
    真實模式：用 yfinance 抓股價並計算報酬率。
    """
    print(f"[fetch_prices] 🌐  yfinance 模式（近 {days} 天）")
    cutoff  = (date.today() - timedelta(days=days)).isoformat()
    price_start = date.today() - timedelta(days=days + 10)
    price_end   = date.today()

    rows = conn.execute(
        """SELECT id, stock_codes, published_at FROM articles
           WHERE sentiment IS NOT NULL
             AND published_at >= ?
           ORDER BY published_at DESC""",
        (cutoff,),
    ).fetchall()

    # 收集所有需要抓價的股票代號
    all_codes: set = set()
    for row in rows:
        try:
            codes = json.loads(row["stock_codes"] or "[]")
            all_codes.update(codes[:2])
        except Exception:
            pass

    price_rows = 0
    for code in all_codes:
        df = fetch_tw_prices(code, price_start, price_end, conn=conn)
        if not df.empty:
            price_rows += len(df)
            print(f"  {code}: {len(df)} 筆")
        else:
            print(f"  {code}: 無資料")

    computed = 0
    for row in rows:
        try:
            codes = json.loads(row["stock_codes"] or "[]")
        except Exception:
            codes = []
        pub_date = row["published_at"][:10]
        for code in codes[:2]:
            result = compute_returns(conn, row["id"], code, pub_date)
            if result.get("return_1d") is not None:
                computed += 1

    print(f"[fetch_prices] 完成：{price_rows} 筆價格，{computed} 筆報酬率")
    return {"price_rows": price_rows, "computed": computed, "mode": "real"}


# ─────────────────────────────────────────────────────────────
# CLI 入口
# ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="抓取台股股價並計算新聞報酬率")
    parser.add_argument("--mock",  action="store_true", help="使用模擬資料（離線展示）")
    parser.add_argument("--days",  type=int, default=30, help="往回幾天的文章（預設 30）")
    parser.add_argument("--db",    type=str, default=str(DEFAULT_DB_PATH), help="資料庫路徑")
    args = parser.parse_args()

    conn = get_connection(Path(args.db))

    if args.mock:
        summary = run_mock(conn, days=args.days)
    else:
        summary = run_real(conn, days=args.days)

    # 顯示驗證資料概況
    df = get_validation_df(conn)
    print(f"\n  驗證資料集：{len(df)} 筆（return_1d 非空）")
    conn.close()


if __name__ == "__main__":
    main()
