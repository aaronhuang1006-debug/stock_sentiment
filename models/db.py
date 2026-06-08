"""
db.py — SQLite 資料庫操作

包含：
- 建立資料表（articles、sentiment_history、pipeline_runs）
- 插入新聞文章（含去重保護）
- 查詢文章
- 更新 AI 分析結果（sentiment、impact_score、reason）
- 記錄 / 查詢 pipeline 執行紀錄
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from models.article import Article

# 預設資料庫路徑，可在 config.py 中覆寫
DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "news.db"


def get_connection(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """建立並回傳 SQLite 連線，自動建立資料夾。"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # 讓查詢結果可以用欄位名稱存取
    return conn


# ---------------------------------------------------------------------------
# 建立資料表
# ---------------------------------------------------------------------------

def create_tables(conn: sqlite3.Connection) -> None:
    """建立所有資料表（若已存在則略過）。"""
    conn.executescript("""
        -- 新聞文章主表
        CREATE TABLE IF NOT EXISTS articles (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            source         TEXT    NOT NULL,           -- 來源：cnyes / yahoo_tw / ...
            title          TEXT    NOT NULL,
            url            TEXT    NOT NULL UNIQUE,    -- 第一層去重：URL 唯一
            published_at   TEXT    NOT NULL,           -- ISO8601 格式
            content        TEXT,
            summary        TEXT,
            stock_codes    TEXT    DEFAULT '[]',       -- JSON 字串，如 '["2330"]'
            content_hash   TEXT    UNIQUE,             -- 第三層去重：內容指紋
            sentiment      TEXT,                       -- 正面 / 負面 / 中立
            impact_score   REAL,                       -- 0.0 – 100.0
            reason         TEXT,                       -- Claude 判斷理由
            keywords       TEXT    DEFAULT '[]',       -- JSON，市場關鍵字 ["AI晶片","CoWoS"]
            crawled_at     TEXT    NOT NULL
        );

        -- 每日情緒歷史表（由 daily_summary.py 寫入）
        CREATE TABLE IF NOT EXISTS sentiment_history (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code      TEXT    NOT NULL,          -- 股票代號，如 '2330'
            date            TEXT    NOT NULL,          -- YYYY-MM-DD
            daily_sentiment REAL,                      -- 當日平均情緒分數
            article_count   INTEGER DEFAULT 0,
            event_summary   TEXT,                      -- Claude 生成的今日事件摘要
            UNIQUE (stock_code, date)                  -- 每支股票每天只有一筆
        );

        -- 使用者帳號表（由 models/auth.py 管理）
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT    NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT    NOT NULL,
            salt          TEXT    NOT NULL,
            created_at    TEXT    NOT NULL,
            watchlist     TEXT    DEFAULT '[]',
            preferences   TEXT    DEFAULT '{}'
        );

        -- 個股日收盤價（由 pipeline/fetch_prices.py 寫入）
        CREATE TABLE IF NOT EXISTS stock_prices (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code  TEXT    NOT NULL,   -- 台股代號，如 "2330"
            date        TEXT    NOT NULL,   -- YYYY-MM-DD
            open        REAL,
            high        REAL,
            low         REAL,
            close       REAL    NOT NULL,
            volume      INTEGER,
            source      TEXT    DEFAULT 'yfinance',
            fetched_at  TEXT    NOT NULL,
            UNIQUE (stock_code, date)
        );

        -- 新聞發布後的個股報酬率（由 pipeline/fetch_prices.py 計算）
        CREATE TABLE IF NOT EXISTS article_returns (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id  INTEGER NOT NULL REFERENCES articles(id),
            stock_code  TEXT    NOT NULL,
            pub_date    TEXT    NOT NULL,   -- 新聞發布日 YYYY-MM-DD
            price_t0    REAL,              -- 發布當日（或下一交易日）收盤價
            price_t1    REAL,              -- T+1 交易日收盤價
            price_t3    REAL,              -- T+3 交易日收盤價
            price_t5    REAL,              -- T+5 交易日收盤價
            return_1d   REAL,              -- (t1-t0)/t0，可為 NULL（資料未到）
            return_3d   REAL,
            return_5d   REAL,
            computed_at TEXT    NOT NULL,
            UNIQUE (article_id, stock_code)
        );

        -- Pipeline 執行紀錄表（由 run_pipeline.py 寫入）
        CREATE TABLE IF NOT EXISTS pipeline_runs (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            ran_at           TEXT    NOT NULL,   -- ISO8601，pipeline 開始時間
            mode             TEXT    NOT NULL,   -- 'mock' 或 'claude'
            crawled_total    INTEGER DEFAULT 0,  -- 爬蟲抓到的文章總數
            inserted         INTEGER DEFAULT 0,  -- 實際寫入 DB 的新文章數
            skipped          INTEGER DEFAULT 0,  -- 重複跳過的文章數
            analyzed         INTEGER DEFAULT 0,  -- 成功分析的文章數
            analysis_failed  INTEGER DEFAULT 0,  -- 分析失敗的文章數
            duration_sec     REAL    DEFAULT 0,  -- 總執行秒數
            error            TEXT                -- 若有致命錯誤，記錄訊息
        );

        -- 常用查詢索引
        CREATE INDEX IF NOT EXISTS idx_articles_source     ON articles (source);
        CREATE INDEX IF NOT EXISTS idx_articles_published  ON articles (published_at DESC);
        CREATE INDEX IF NOT EXISTS idx_pipeline_runs_at    ON pipeline_runs (ran_at DESC);
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# 插入文章
# ---------------------------------------------------------------------------

def insert_article(conn: sqlite3.Connection, article: Article) -> bool:
    """
    插入一篇文章。
    若 URL 或 content_hash 已存在（重複），則略過並回傳 False。
    成功插入回傳 True。
    """
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO articles
                (source, title, url, published_at, content, summary,
                 stock_codes, content_hash, sentiment, impact_score, reason,
                 keywords, crawled_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                article.source,
                article.title,
                article.url,
                article.published_at.isoformat(),
                article.content,
                article.summary,
                json.dumps(article.stock_codes, ensure_ascii=False),
                article.content_hash,
                article.sentiment,
                article.impact_score,
                article.reason,
                json.dumps(getattr(article, "keywords", []), ensure_ascii=False),
                article.crawled_at.isoformat(),
            ),
        )
        conn.commit()
        # rowcount == 0 表示被 IGNORE（重複），== 1 表示成功插入
        return conn.execute("SELECT changes()").fetchone()[0] > 0
    except sqlite3.Error as e:
        print(f"[db] 插入失敗 ({article.url}): {e}")
        return False


def insert_articles(conn: sqlite3.Connection, articles: list[Article]) -> int:
    """批次插入，回傳實際寫入的筆數（去重後）。"""
    inserted = sum(insert_article(conn, a) for a in articles)
    return inserted


# ---------------------------------------------------------------------------
# 查詢文章
# ---------------------------------------------------------------------------

def fetch_articles(
    conn: sqlite3.Connection,
    source: Optional[str] = None,
    stock_code: Optional[str] = None,
    since: Optional[datetime] = None,
    limit: int = 100,
) -> list[sqlite3.Row]:
    """
    查詢文章，支援以下篩選條件（可組合使用）：
    - source     : 指定來源，如 'cnyes'
    - stock_code : 指定股票代號，如 '2330'（模糊比對 stock_codes JSON 欄位）
    - since      : 只撈此時間之後的文章
    - limit      : 最多回傳幾筆
    """
    conditions = []
    params: list = []

    if source:
        conditions.append("source = ?")
        params.append(source)

    if stock_code:
        # stock_codes 是 JSON 字串，用 LIKE 做簡單模糊比對
        conditions.append("stock_codes LIKE ?")
        params.append(f'%"{stock_code}"%')

    if since:
        conditions.append("published_at >= ?")
        params.append(since.isoformat())

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)

    rows = conn.execute(
        f"SELECT * FROM articles {where} ORDER BY published_at DESC LIMIT ?",
        params,
    ).fetchall()
    return rows


def fetch_unanalyzed(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    """查詢尚未做 AI 分析的文章（sentiment 為 NULL）。"""
    return conn.execute(
        "SELECT * FROM articles WHERE sentiment IS NULL ORDER BY published_at DESC LIMIT ?",
        (limit,),
    ).fetchall()


# ---------------------------------------------------------------------------
# 更新 AI 分析結果
# ---------------------------------------------------------------------------

def update_sentiment(
    conn: sqlite3.Connection,
    article_id: int,
    sentiment: str,
    impact_score: float,
    reason: str,
    keywords: Optional[list] = None,
) -> None:
    """
    將 Claude API 的分析結果寫回 articles 表。
    keywords 為可選參數，傳入時一併更新；不傳則不覆蓋原有 keywords。
    由 analysis/sentiment.py 呼叫。
    """
    if keywords is not None:
        conn.execute(
            """
            UPDATE articles
            SET sentiment = ?, impact_score = ?, reason = ?, keywords = ?
            WHERE id = ?
            """,
            (sentiment, impact_score, reason,
             json.dumps(keywords, ensure_ascii=False), article_id),
        )
    else:
        conn.execute(
            """
            UPDATE articles
            SET sentiment = ?, impact_score = ?, reason = ?
            WHERE id = ?
            """,
            (sentiment, impact_score, reason, article_id),
        )
    conn.commit()


def update_keywords(
    conn: sqlite3.Connection,
    article_id: int,
    keywords: list,
) -> None:
    """
    只補寫 keywords 欄位，不覆蓋 sentiment / impact_score / reason。
    用於舊資料 migration：文章已有 sentiment 但 keywords 為空的情況。
    """
    conn.execute(
        "UPDATE articles SET keywords = ? WHERE id = ?",
        (json.dumps(keywords, ensure_ascii=False), article_id),
    )
    conn.commit()


def fetch_keywords_missing(
    conn: sqlite3.Connection,
    limit: int = 50,
) -> list:
    """
    查詢「已有 sentiment 但 keywords 為空陣列或 NULL」的文章。
    用於只補 keywords 的 migration 模式。
    """
    return conn.execute(
        """SELECT * FROM articles
           WHERE sentiment IS NOT NULL
             AND (keywords IS NULL OR keywords = '[]')
           ORDER BY published_at DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()


# ---------------------------------------------------------------------------
# Pipeline 執行紀錄
# ---------------------------------------------------------------------------

def record_pipeline_run(
    conn: sqlite3.Connection,
    ran_at: datetime,
    mode: str,
    crawled_total: int,
    inserted: int,
    skipped: int,
    analyzed: int,
    analysis_failed: int,
    duration_sec: float,
    error: Optional[str] = None,
) -> int:
    """
    寫入一筆 pipeline 執行紀錄，回傳新記錄的 id。
    由 run_pipeline.py 在每次執行結束後呼叫。
    """
    cursor = conn.execute(
        """
        INSERT INTO pipeline_runs
            (ran_at, mode, crawled_total, inserted, skipped,
             analyzed, analysis_failed, duration_sec, error)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ran_at.isoformat(),
            mode,
            crawled_total,
            inserted,
            skipped,
            analyzed,
            analysis_failed,
            round(duration_sec, 2),
            error,
        ),
    )
    conn.commit()
    return cursor.lastrowid


def get_latest_pipeline_run(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    """
    回傳最近一次 pipeline 執行紀錄，無紀錄時回傳 None。
    Dashboard 用來顯示 Last Updated 等資訊。
    """
    return conn.execute(
        "SELECT * FROM pipeline_runs ORDER BY ran_at DESC LIMIT 1"
    ).fetchone()


def count_articles(conn: sqlite3.Connection) -> int:
    """回傳 articles 表的總筆數。"""
    row = conn.execute("SELECT COUNT(*) FROM articles").fetchone()
    return row[0] if row else 0
