"""
run_pipeline.py — 台股新聞 AI 情緒追蹤器統一執行入口

功能：
  1. 依序執行所有已登記的爬蟲
  2. 批次執行情緒分析（mock 或 claude 模式）
  3. 記錄執行結果到 pipeline_runs 表
  4. 輸出清楚的執行摘要

執行方式：
    cd ~/Desktop/stock_sentiment

    # Mock 模式（關鍵字分析，不呼叫 Claude API）
    python3 run_pipeline.py --mock

    # Claude 模式（呼叫 Claude API，需要 ANTHROPIC_API_KEY）
    python3 run_pipeline.py --claude

    # 指定分析上限（預設 30 篇）
    python3 run_pipeline.py --mock --analysis-limit 50

    # 只跑爬蟲不分析
    python3 run_pipeline.py --mock --crawl-only

擴充新爬蟲：
    在下方 CRAWLERS 清單新增一行，主流程不需要任何修改。
    格式：(爬蟲類別, 初始化參數 dict)
"""

import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# ── UTF-8 stdout（Python 3.9 pipe 環境必要）──────────────────
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent))

from crawlers.cnyes import CnyesCrawler
from crawlers.yahoo_tw import YahooTwCrawler
from models.db import (
    count_articles,
    create_tables,
    fetch_unanalyzed,
    get_connection,
    insert_article,
    record_pipeline_run,
    update_sentiment,
)

# ─────────────────────────────────────────────────────────────
# Crawler 登記表
# 新增來源：只需在這裡加一行，格式 (類別, 初始化 kwargs)
# 主流程的 run_crawlers() 完全不需要修改。
# ─────────────────────────────────────────────────────────────
CRAWLERS: list[tuple[type, dict]] = [
    (CnyesCrawler,   {"limit": 30}),
    (YahooTwCrawler, {}),
]

DB_PATH = Path(__file__).parent / "data" / "news.db"

# 分析模式預設批次上限
DEFAULT_ANALYSIS_LIMIT = 30
# 每篇 Claude 呼叫之間的間隔（秒）
CLAUDE_REQUEST_DELAY   = 1.5


# ─────────────────────────────────────────────────────────────
# 資料結構
# ─────────────────────────────────────────────────────────────

@dataclass
class CrawlResult:
    """單一爬蟲的執行結果。"""
    source:   str
    fetched:  int = 0   # 爬到的文章數
    inserted: int = 0   # 實際寫入 DB 數
    skipped:  int = 0   # 重複跳過數
    error:    str = ""  # 若有錯誤，記錄訊息


@dataclass
class PipelineResult:
    """整個 pipeline 的執行摘要。"""
    mode:            str = ""
    crawl_results:   list[CrawlResult] = field(default_factory=list)
    analyzed:        int = 0
    analysis_failed: int = 0
    duration_sec:    float = 0.0
    fatal_error:     str = ""

    # ── 彙總屬性 ─────────────────────────────────────────────
    @property
    def total_fetched(self) -> int:
        return sum(r.fetched for r in self.crawl_results)

    @property
    def total_inserted(self) -> int:
        return sum(r.inserted for r in self.crawl_results)

    @property
    def total_skipped(self) -> int:
        return sum(r.skipped for r in self.crawl_results)


# ─────────────────────────────────────────────────────────────
# 工具函式
# ─────────────────────────────────────────────────────────────

def _sep(label: str = "", width: int = 44) -> None:
    if label:
        print(f"── {label} " + "─" * max(0, width - len(label) - 4))
    else:
        print("─" * width)


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


# ─────────────────────────────────────────────────────────────
# 核心步驟
# ─────────────────────────────────────────────────────────────

def run_crawlers(conn) -> list[CrawlResult]:
    """
    依序執行 CRAWLERS 清單中的所有爬蟲。
    任一爬蟲失敗時記錄 error 並繼續下一個，不中斷整體流程。
    """
    results: list[CrawlResult] = []

    for crawler_cls, kwargs in CRAWLERS:
        result = CrawlResult(source=crawler_cls.source)
        _sep(f"Crawler: {crawler_cls.source}")

        try:
            crawler = crawler_cls(**kwargs)
            articles = crawler.run()
            result.fetched = len(articles)

            for article in articles:
                if insert_article(conn, article):
                    result.inserted += 1
                else:
                    result.skipped += 1

            _log(f"抓到 {result.fetched} 篇 → 新增 {result.inserted}，跳過 {result.skipped}")

        except Exception:
            result.error = traceback.format_exc(limit=3)
            _log(f"[錯誤] {crawler_cls.source} 爬蟲失敗：")
            print(result.error)

        results.append(result)

    return results


def run_analysis(conn, mode: str, limit: int) -> tuple[int, int]:
    """
    對未分析的文章執行情緒分析。
    回傳 (成功數, 失敗數)。
    mode: 'mock' | 'claude'
    """
    import json as _json

    rows = fetch_unanalyzed(conn, limit=limit)
    if not rows:
        _log("沒有待分析文章。")
        return 0, 0

    _sep(f"Analysis ({mode.upper()} 模式)")
    _log(f"待分析 {len(rows)} 篇")

    # ── 初始化分析器 ────────────────────────────────────────
    if mode == "mock":
        from analysis.mock_sentiment import mock_analyze
        analyzer = None
    else:
        try:
            from analysis.sentiment import SentimentAnalyzer
            analyzer = SentimentAnalyzer()
        except EnvironmentError as e:
            _log(f"[錯誤] Claude 分析器初始化失敗：{e}")
            return 0, len(rows)

    succeeded = 0
    failed    = 0

    for i, row in enumerate(rows, 1):
        article_id  = row["id"]
        title       = row["title"]
        content     = row["content"]
        try:
            stock_codes = _json.loads(row["stock_codes"] or "[]")
        except Exception:
            stock_codes = []

        short_title = title[:45] + ("…" if len(title) > 45 else "")
        print(f"  [{i:02d}/{len(rows):02d}] {short_title}")

        try:
            if mode == "mock":
                result = mock_analyze(title=title, content=content,
                                      stock_codes=stock_codes)
            else:
                result = analyzer.analyze(title=title, content=content,
                                          stock_codes=stock_codes)

            update_sentiment(
                conn,
                article_id=article_id,
                sentiment=result.sentiment,
                impact_score=result.impact_score,
                reason=result.reason,
            )
            print(f"         → {result.sentiment}  {result.impact_score:.0f}/10")
            succeeded += 1

        except Exception:
            err_short = traceback.format_exc(limit=1).strip().splitlines()[-1]
            print(f"         → [錯誤] {err_short}")
            failed += 1

        if mode == "claude" and i < len(rows):
            time.sleep(CLAUDE_REQUEST_DELAY)

    return succeeded, failed


def print_summary(result: PipelineResult, db_total: int) -> None:
    """印出整體執行摘要。"""
    _sep()
    print("  台股新聞 AI 情緒追蹤器｜Pipeline 執行摘要")
    _sep()
    print(f"  執行模式  : {result.mode.upper()}")
    print(f"  執行時間  : {result.duration_sec:.1f} 秒")
    print()
    print("  ── 爬蟲 ─────────────────────────────")
    for r in result.crawl_results:
        status = "✓" if not r.error else "✗"
        print(f"  {status} {r.source:<14} "
              f"抓到 {r.fetched:>3} 篇 / 新增 {r.inserted:>3} / 跳過 {r.skipped:>3}")
        if r.error:
            print(f"    └─ 錯誤：{r.error.splitlines()[-1]}")
    print()
    print("  ── 分析 ─────────────────────────────")
    print(f"  成功   : {result.analyzed} 篇")
    print(f"  失敗   : {result.analysis_failed} 篇")
    print()
    print("  ── 資料庫 ───────────────────────────")
    print(f"  文章總數 : {db_total} 篇")
    if result.fatal_error:
        print()
        print(f"  ⚠ 致命錯誤：{result.fatal_error}")
    _sep()


# ─────────────────────────────────────────────────────────────
# 參數解析
# ─────────────────────────────────────────────────────────────

def _parse_args() -> tuple[str, int, bool]:
    """
    回傳 (mode, analysis_limit, crawl_only)。
    mode: 'mock'（預設）或 'claude'
    """
    args = sys.argv[1:]

    if "--claude" in args:
        mode = "claude"
    else:
        mode = "mock"   # 預設安全模式

    crawl_only = "--crawl-only" in args

    limit = DEFAULT_ANALYSIS_LIMIT
    if "--analysis-limit" in args:
        idx = args.index("--analysis-limit")
        try:
            limit = int(args[idx + 1])
        except (IndexError, ValueError):
            print("[錯誤] --analysis-limit 後面必須接整數，例如 --analysis-limit 20")
            sys.exit(1)

    return mode, limit, crawl_only


# ─────────────────────────────────────────────────────────────
# 主程式
# ─────────────────────────────────────────────────────────────

def main() -> None:
    mode, analysis_limit, crawl_only = _parse_args()
    started_at = datetime.now()

    _sep()
    _log(f"Pipeline 開始 | 模式：{mode.upper()} | 分析上限：{analysis_limit}")
    _sep()

    pipeline = PipelineResult(mode=mode)
    conn     = None

    try:
        conn = get_connection(DB_PATH)
        create_tables(conn)

        # ── Step 1：爬蟲 ────────────────────────────────────
        pipeline.crawl_results = run_crawlers(conn)

        # ── Step 2：分析（除非 --crawl-only）────────────────
        if not crawl_only:
            ok, fail = run_analysis(conn, mode=mode, limit=analysis_limit)
            pipeline.analyzed        = ok
            pipeline.analysis_failed = fail
        else:
            _log("--crawl-only 模式：跳過分析步驟。")

        # ── Step 3：記錄執行結果 ─────────────────────────────
        pipeline.duration_sec = time.time() - started_at.timestamp()
        db_total = count_articles(conn)

        record_pipeline_run(
            conn,
            ran_at           = started_at,
            mode             = mode,
            crawled_total    = pipeline.total_fetched,
            inserted         = pipeline.total_inserted,
            skipped          = pipeline.total_skipped,
            analyzed         = pipeline.analyzed,
            analysis_failed  = pipeline.analysis_failed,
            duration_sec     = pipeline.duration_sec,
            error            = None,
        )

    except Exception:
        pipeline.fatal_error  = traceback.format_exc(limit=3)
        pipeline.duration_sec = time.time() - started_at.timestamp()
        db_total              = 0
        _log("[致命錯誤] Pipeline 中斷：")
        print(pipeline.fatal_error)

        if conn:
            try:
                record_pipeline_run(
                    conn,
                    ran_at           = started_at,
                    mode             = mode,
                    crawled_total    = pipeline.total_fetched,
                    inserted         = pipeline.total_inserted,
                    skipped          = pipeline.total_skipped,
                    analyzed         = pipeline.analyzed,
                    analysis_failed  = pipeline.analysis_failed,
                    duration_sec     = pipeline.duration_sec,
                    error            = pipeline.fatal_error[-500:],  # 截短避免過長
                )
            except Exception:
                pass

    finally:
        if conn:
            conn.close()

    print_summary(pipeline, db_total)


if __name__ == "__main__":
    main()
