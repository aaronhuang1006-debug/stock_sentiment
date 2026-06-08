"""
price.py — 個股股價抓取、儲存與報酬率計算

主要功能：
  1. fetch_tw_prices()    — yfinance 抓台股日收盤，寫入 stock_prices 表
  2. compute_returns()    — 計算文章發布後 1/3/5 交易日報酬率，寫入 article_returns
  3. get_validation_df()  — 讀取已計算的驗證資料，供 Dashboard 使用

台股 ticker 格式：
  上市（TWSE）：{code}.TW   ex. 2330.TW
  上櫃（TPEx）：{code}.TWO  ex. 6488.TWO
  ETF：0050.TW, 0056.TW（同上市格式）
"""

import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "news.db"

# 不抓股價的黑名單（純指數、境外 ETF 等）
_SKIP_CODES = {"0050", "0056", "00878", "00929", "00919"}


# ─────────────────────────────────────────────────────────────
# yfinance 工具
# ─────────────────────────────────────────────────────────────

def _to_yf_ticker(stock_code: str) -> Optional[str]:
    """
    台股代號 → yfinance ticker。
    先試 .TW（上市），失敗後呼叫方可再試 .TWO（上櫃）。
    ETF / 黑名單代號直接用 .TW。
    """
    return f"{stock_code}.TW"


def fetch_tw_prices(
    stock_code: str,
    start: date,
    end: date,
    conn: Optional[sqlite3.Connection] = None,
) -> pd.DataFrame:
    """
    用 yfinance 抓指定台股代號的日 OHLCV，
    回傳 DataFrame（columns: date, open, high, low, close, volume）。
    抓取失敗時回傳空 DataFrame，不拋例外。

    若傳入 conn，會同時把資料寫入 stock_prices 表。
    """
    try:
        import yfinance as yf
    except ImportError:
        print("[price] yfinance 未安裝，請執行 pip3 install yfinance")
        return pd.DataFrame()

    fetched_at = datetime.now().isoformat()

    # 先試 .TW，失敗再試 .TWO
    for suffix in (".TW", ".TWO"):
        ticker_str = f"{stock_code}{suffix}"
        try:
            raw = yf.download(
                ticker_str,
                start=start.isoformat(),
                end=(end + timedelta(days=1)).isoformat(),   # end 是 exclusive
                auto_adjust=True,
                progress=False,
                multi_level_column=False,
            )
            if raw is None or raw.empty:
                continue

            # 整理欄位
            df = raw.reset_index()
            # yfinance 1.x column names
            rename = {}
            for col in df.columns:
                cl = str(col).lower()
                if "date" in cl:
                    rename[col] = "date"
                elif "open" in cl:
                    rename[col] = "open"
                elif "high" in cl:
                    rename[col] = "high"
                elif "low" in cl:
                    rename[col] = "low"
                elif "close" in cl:
                    rename[col] = "close"
                elif "volume" in cl:
                    rename[col] = "volume"
            df = df.rename(columns=rename)

            needed = {"date", "close"}
            if not needed.issubset(df.columns):
                continue

            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
            df = df.dropna(subset=["close"])

            if conn is not None:
                _store_prices(conn, stock_code, df, fetched_at)

            return df[list({"date", "open", "high", "low", "close", "volume"} & set(df.columns))]

        except Exception as e:
            print(f"[price] {ticker_str} 抓取失敗：{e}")
            continue

    return pd.DataFrame()


def _store_prices(
    conn: sqlite3.Connection,
    stock_code: str,
    df: pd.DataFrame,
    fetched_at: str,
) -> int:
    """把 OHLCV DataFrame 批次寫入 stock_prices 表，回傳寫入筆數。"""
    inserted = 0
    for _, row in df.iterrows():
        try:
            conn.execute(
                """INSERT OR IGNORE INTO stock_prices
                     (stock_code, date, open, high, low, close, volume, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    stock_code,
                    row["date"],
                    float(row.get("open") or 0) or None,
                    float(row.get("high") or 0) or None,
                    float(row.get("low") or 0) or None,
                    float(row["close"]),
                    int(row.get("volume") or 0) or None,
                    fetched_at,
                ),
            )
            if conn.execute("SELECT changes()").fetchone()[0]:
                inserted += 1
        except Exception:
            pass
    conn.commit()
    return inserted


# ─────────────────────────────────────────────────────────────
# 報酬率計算
# ─────────────────────────────────────────────────────────────

def _get_price_on_or_after(
    conn: sqlite3.Connection,
    stock_code: str,
    from_date: str,
    offset_days: int = 0,
) -> Optional[float]:
    """
    取得 from_date 之後的第 offset_days 個交易日的收盤價。
    offset_days=0 → from_date 當天或之後最近交易日
    offset_days=1 → 第 1 個交易日後
    回傳 None 表示資料不足。
    """
    rows = conn.execute(
        """SELECT close FROM stock_prices
           WHERE stock_code = ? AND date >= ?
           ORDER BY date ASC""",
        (stock_code, from_date),
    ).fetchall()

    if len(rows) <= offset_days:
        return None
    return float(rows[offset_days]["close"])


def compute_returns(
    conn: sqlite3.Connection,
    article_id: int,
    stock_code: str,
    pub_date: str,          # YYYY-MM-DD
) -> dict:
    """
    計算單篇文章 × 單一股票的 1/3/5 日報酬率。
    結果寫入 article_returns 表，並回傳 dict。
    """
    computed_at = datetime.now().isoformat()

    p0 = _get_price_on_or_after(conn, stock_code, pub_date, 0)
    p1 = _get_price_on_or_after(conn, stock_code, pub_date, 1)
    p3 = _get_price_on_or_after(conn, stock_code, pub_date, 3)
    p5 = _get_price_on_or_after(conn, stock_code, pub_date, 5)

    def _ret(p_n: Optional[float]) -> Optional[float]:
        if p0 and p_n and p0 > 0:
            return round((p_n - p0) / p0 * 100, 4)  # 百分比
        return None

    r1, r3, r5 = _ret(p1), _ret(p3), _ret(p5)

    try:
        conn.execute(
            """INSERT OR REPLACE INTO article_returns
                 (article_id, stock_code, pub_date,
                  price_t0, price_t1, price_t3, price_t5,
                  return_1d, return_3d, return_5d, computed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (article_id, stock_code, pub_date, p0, p1, p3, p5, r1, r3, r5, computed_at),
        )
        conn.commit()
    except Exception as e:
        print(f"[price] 寫入 article_returns 失敗：{e}")

    return {"return_1d": r1, "return_3d": r3, "return_5d": r5, "price_t0": p0}


# ─────────────────────────────────────────────────────────────
# 驗證資料查詢
# ─────────────────────────────────────────────────────────────

def get_validation_df(conn: sqlite3.Connection) -> pd.DataFrame:
    """
    JOIN articles + article_returns，回傳驗證用 DataFrame。
    columns: article_id, title, sentiment, impact_score,
             stock_code, pub_date, return_1d, return_3d, return_5d
    只回傳 return_1d IS NOT NULL 的筆數（即股價資料已到位的）。
    """
    sql = """
        SELECT
            ar.article_id,
            a.title,
            a.sentiment,
            a.impact_score,
            ar.stock_code,
            ar.pub_date,
            ar.return_1d,
            ar.return_3d,
            ar.return_5d
        FROM article_returns ar
        JOIN articles a ON ar.article_id = a.id
        WHERE ar.return_1d IS NOT NULL
          AND a.sentiment  IS NOT NULL
          AND a.impact_score IS NOT NULL
        ORDER BY ar.pub_date DESC
    """
    try:
        return pd.read_sql_query(sql, conn)
    except Exception:
        return pd.DataFrame()
