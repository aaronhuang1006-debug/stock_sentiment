"""
update_all.py — one-command update pipeline.

執行方式：
    cd ~/Desktop/stock_sentiment
    python3 pipeline/update_all.py

可選：
    python3 pipeline/update_all.py --mock          # mock AI + mock prices
    python3 pipeline/update_all.py --limit 20      # 最多分析 20 篇待分析文章
    python3 pipeline/update_all.py --days 90       # 價格驗證往回 90 天

流程：
  1. 抓取所有新聞來源並寫入 DB
  2. 分析 sentiment 或 impact_score 尚未完成的新聞
  3. 抓取 Price Validation 所需價格並計算報酬率

不修改 DB schema，不修改 crawler，不修改 dashboard。
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from analysis.mock_sentiment import mock_analyze
from analysis.sentiment import SentimentAnalyzer
from crawlers.cna_finance import CnaFinanceCrawler
from crawlers.cnyes import CnyesCrawler
from crawlers.ctee import CteeCrawler
from crawlers.money_udn import MoneyUdnCrawler
from crawlers.moneydj import MoneyDjCrawler
from crawlers.yahoo_tw import YahooTwCrawler
from models.article import Article
from models.db import (
    create_tables,
    get_connection,
    insert_article,
    record_pipeline_run,
    update_sentiment,
)
from pipeline import fetch_prices
from pipeline.analyze_sentiment import REQUEST_DELAY
from pipeline.save_finance_sources_to_db import _dedupe_articles

DB_PATH = ROOT / "data" / "news.db"


def _count(conn, sql: str, params: tuple = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row[0]) if row else 0


def _stage_header(title: str) -> None:
    print()
    print(f"── {title} ─────────────────────────")


def crawl_all_sources(conn) -> dict:
    _stage_header("階段 1 / 3：抓取所有新聞來源")

    crawler_specs = [
        ("鉅亨網", CnyesCrawler(limit=30)),
        ("Yahoo 股市", YahooTwCrawler()),
        ("工商時報", CteeCrawler(limit=30)),
        ("經濟日報", MoneyUdnCrawler(limit=30)),
        ("MoneyDJ", MoneyDjCrawler(limit=30)),
        ("中央社財經", CnaFinanceCrawler(limit=30)),
    ]

    all_articles: list[Article] = []
    failures: list[str] = []

    for label, crawler in crawler_specs:
        try:
            articles = crawler.run()
            articles = _dedupe_articles(articles)
            print(f"[{crawler.source}] {label}: 抓到 {len(articles)} 篇")
            all_articles.extend(articles)
        except Exception as e:
            msg = f"[{crawler.source}] {label} 失敗: {e}"
            print(msg)
            failures.append(msg)

    deduped = _dedupe_articles(all_articles)
    inserted = skipped = 0
    for article in deduped:
        if insert_article(conn, article):
            inserted += 1
        else:
            skipped += 1

    print()
    print("新聞抓取結果")
    print(f"  批次去重後 : {len(deduped)} 篇")
    print(f"  新增       : {inserted} 篇")
    print(f"  跳過       : {skipped} 篇（URL/title/content_hash 重複）")
    if failures:
        print("  失敗來源   :")
        for failure in failures:
            print(f"    - {failure}")

    return {
        "crawled_total": len(deduped),
        "inserted": inserted,
        "skipped": skipped,
        "failures": failures,
    }


def _fetch_pending_analysis_rows(conn, limit: Optional[int] = None) -> list:
    sql = """
        SELECT *
        FROM articles
        WHERE sentiment IS NULL OR impact_score IS NULL
        ORDER BY published_at DESC
    """
    params: tuple = ()
    if limit is not None:
        sql += " LIMIT ?"
        params = (limit,)
    return conn.execute(sql, params).fetchall()


def analyze_pending_articles(conn, mock: bool = False, limit: Optional[int] = None) -> dict:
    _stage_header("階段 2 / 3：分析尚未分析新聞")

    total_articles = _count(conn, "SELECT COUNT(*) FROM articles")
    pending_total = _count(
        conn,
        "SELECT COUNT(*) FROM articles WHERE sentiment IS NULL OR impact_score IS NULL",
    )
    rows = _fetch_pending_analysis_rows(conn, limit=limit)
    skipped = max(total_articles - pending_total, 0)

    print(f"待分析 : {pending_total} 篇")
    print(f"本次處理 : {len(rows)} 篇" + (f"（limit={limit}）" if limit is not None else ""))
    print(f"跳過已分析 : {skipped} 篇")

    if not rows:
        return {"analyzed": 0, "failed": 0, "skipped": skipped, "failures": []}

    analyzer = None
    failures: list[str] = []
    if not mock:
        try:
            analyzer = SentimentAnalyzer()
        except EnvironmentError as e:
            msg = f"初始化 AI analyzer 失敗: {e}"
            print(msg)
            failures.append(msg)
            return {"analyzed": 0, "failed": len(rows), "skipped": skipped, "failures": failures}

    succeeded = failed = 0
    for i, row in enumerate(rows, 1):
        title = row["title"]
        content = row["content"]
        try:
            stock_codes = json.loads(row["stock_codes"] or "[]")
        except (json.JSONDecodeError, TypeError):
            stock_codes = []

        print(f"[{i}/{len(rows)}] {title[:50]}{'…' if len(title) > 50 else ''}")
        try:
            if mock:
                result = mock_analyze(title=title, content=content, stock_codes=stock_codes)
            else:
                result = analyzer.analyze(  # type: ignore[union-attr]
                    title=title,
                    content=content,
                    stock_codes=stock_codes,
                )

            update_sentiment(
                conn,
                article_id=row["id"],
                sentiment=result.sentiment,
                impact_score=result.impact_score,
                reason=result.reason,
                keywords=result.keywords,
            )
            print(f"         → {result.sentiment} {result.impact_score:.0f}/10")
            succeeded += 1
        except Exception as e:
            msg = f"文章 {row['id']} 分析失敗: {e}"
            print(f"         → [錯誤] {e}")
            failures.append(msg)
            failed += 1

        if i < len(rows) and not mock:
            time.sleep(REQUEST_DELAY)

    print()
    print("分析結果")
    print(f"  成功 : {succeeded} 篇")
    print(f"  失敗 : {failed} 篇")
    print(f"  跳過 : {skipped} 篇")

    return {"analyzed": succeeded, "failed": failed, "skipped": skipped, "failures": failures}


def update_price_validation(conn, mock: bool = False, days: int = 30) -> dict:
    _stage_header("階段 3 / 3：更新 Price Validation")

    before = _count(conn, "SELECT COUNT(*) FROM article_returns WHERE return_1d IS NOT NULL")
    try:
        if mock:
            summary = fetch_prices.run_mock(conn, days=days)
        else:
            summary = fetch_prices.run_real(conn, days=days)
    except Exception as e:
        print(f"[fetch_prices] 失敗: {e}")
        return {
            "price_rows": 0,
            "computed": 0,
            "new_validation_rows": 0,
            "failed": True,
            "error": str(e),
        }

    after = _count(conn, "SELECT COUNT(*) FROM article_returns WHERE return_1d IS NOT NULL")
    new_rows = max(after - before, 0)

    print()
    print("價格驗證結果")
    print(f"  價格資料更新 : {summary.get('price_rows', 0)} 筆")
    print(f"  報酬率計算   : {summary.get('computed', 0)} 筆")
    print(f"  新增驗證資料 : {new_rows} 筆")

    return {
        "price_rows": summary.get("price_rows", 0),
        "computed": summary.get("computed", 0),
        "new_validation_rows": new_rows,
        "failed": False,
        "error": None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="抓新聞 → AI 分析 → Price Validation")
    parser.add_argument("--mock", action="store_true", help="使用 mock AI 與 mock prices")
    parser.add_argument("--limit", type=int, default=None, help="最多分析幾篇待分析文章")
    parser.add_argument("--days", type=int, default=30, help="價格驗證往回幾天文章")
    args = parser.parse_args()

    started = datetime.now()
    errors: list[str] = []
    conn = get_connection(DB_PATH)
    create_tables(conn)

    crawl_summary = {"crawled_total": 0, "inserted": 0, "skipped": 0, "failures": []}
    analysis_summary = {"analyzed": 0, "failed": 0, "skipped": 0, "failures": []}
    price_summary = {"price_rows": 0, "computed": 0, "new_validation_rows": 0, "failed": False, "error": None}

    try:
        try:
            crawl_summary = crawl_all_sources(conn)
            errors.extend(crawl_summary.get("failures", []))
        except Exception as e:
            msg = f"新聞抓取階段失敗: {e}"
            print(msg)
            errors.append(msg)

        try:
            analysis_summary = analyze_pending_articles(conn, mock=args.mock, limit=args.limit)
            errors.extend(analysis_summary.get("failures", []))
        except Exception as e:
            msg = f"AI 分析階段失敗: {e}"
            print(msg)
            errors.append(msg)

        try:
            price_summary = update_price_validation(conn, mock=args.mock, days=args.days)
            if price_summary.get("error"):
                errors.append(str(price_summary["error"]))
        except Exception as e:
            msg = f"價格驗證階段失敗: {e}"
            print(msg)
            errors.append(msg)

        duration = (datetime.now() - started).total_seconds()
        try:
            record_pipeline_run(
                conn,
                ran_at=started,
                mode="mock" if args.mock else "real",
                crawled_total=int(crawl_summary.get("crawled_total", 0)),
                inserted=int(crawl_summary.get("inserted", 0)),
                skipped=int(crawl_summary.get("skipped", 0)),
                analyzed=int(analysis_summary.get("analyzed", 0)),
                analysis_failed=int(analysis_summary.get("failed", 0)),
                duration_sec=duration,
                error="; ".join(errors) if errors else None,
            )
        except Exception as e:
            print(f"[pipeline_runs] 紀錄失敗: {e}")

        print()
        print("── 一鍵更新完成 ───────────────────────")
        print(f"  新聞新增       : {crawl_summary.get('inserted', 0)} 篇")
        print(f"  新聞跳過       : {crawl_summary.get('skipped', 0)} 篇")
        print(f"  AI 分析成功    : {analysis_summary.get('analyzed', 0)} 篇")
        print(f"  AI 分析失敗    : {analysis_summary.get('failed', 0)} 篇")
        print(f"  價格資料更新   : {price_summary.get('price_rows', 0)} 筆")
        print(f"  價格驗證計算   : {price_summary.get('computed', 0)} 筆")
        print(f"  新增驗證資料   : {price_summary.get('new_validation_rows', 0)} 筆")
        if errors:
            print("  失敗原因       :")
            for error in errors:
                print(f"    - {error}")
        else:
            print("  失敗原因       : 無")
        print(f"  耗時           : {duration:.1f}s")
        print("──────────────────────────────────────")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
