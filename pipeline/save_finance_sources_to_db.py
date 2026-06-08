"""
save_finance_sources_to_db.py — crawl additional Taiwan finance news sources.

執行方式：
    cd ~/Desktop/stock_sentiment
    python3 pipeline/save_finance_sources_to_db.py

新增來源：
    - 工商時報 ctee
    - 經濟日報 money_udn
    - MoneyDJ moneydj
    - 中央社財經 cna_finance
"""

import sys
from pathlib import Path
from typing import Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent.parent))

from crawlers.cna_finance import CnaFinanceCrawler
from crawlers.ctee import CteeCrawler
from crawlers.money_udn import MoneyUdnCrawler
from crawlers.moneydj import MoneyDjCrawler
from models.article import Article
from models.db import create_tables, get_connection, insert_article

DB_PATH = Path(__file__).parent.parent / "data" / "news.db"


def _dedupe_articles(articles: list[Article]) -> list[Article]:
    """Deduplicate within this crawl batch by URL first, then normalized title."""
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    result: list[Article] = []

    for article in articles:
        url_key = (article.url or "").strip()
        title_key = "".join((article.title or "").split()).lower()
        if url_key and url_key in seen_urls:
            continue
        if title_key and title_key in seen_titles:
            continue

        if url_key:
            seen_urls.add(url_key)
        if title_key:
            seen_titles.add(title_key)
        result.append(article)

    return result


def main() -> None:
    conn = get_connection(DB_PATH)
    create_tables(conn)

    crawler_specs = [
        ("工商時報", CteeCrawler(limit=30)),
        ("經濟日報", MoneyUdnCrawler(limit=30)),
        ("MoneyDJ", MoneyDjCrawler(limit=30)),
        ("中央社財經", CnaFinanceCrawler(limit=30)),
    ]

    source_stats: list[tuple[str, int, int, int, Optional[str]]] = []
    all_articles: list[Article] = []

    for label, crawler in crawler_specs:
        try:
            articles = crawler.run()
            articles = _dedupe_articles(articles)
            print(f"[{crawler.source}] {label} 去重後 {len(articles)} 篇")
            source_stats.append((label, len(articles), 0, 0, None))
            all_articles.extend(articles)
        except Exception as e:
            # 保護整體 pipeline：單一來源失敗不影響其他來源。
            print(f"[{crawler.source}] {label} 失敗: {e}")
            source_stats.append((label, 0, 0, 0, str(e)))

    inserted = skipped = 0
    for article in _dedupe_articles(all_articles):
        if insert_article(conn, article):
            inserted += 1
        else:
            skipped += 1

    conn.close()

    print()
    print("── 新增財經來源執行結果 ─────────────────")
    for label, crawled, _inserted, _skipped, error in source_stats:
        if error:
            print(f"  {label}: 失敗，原因：{error}")
        else:
            print(f"  {label}: 抓到 {crawled} 篇")
    print(f"  DB 新增 : {inserted} 篇")
    print(f"  DB 跳過 : {skipped} 篇（URL/title/content_hash 重複）")
    print(f"  DB 位置 : {DB_PATH}")
    print("──────────────────────────────────────")


if __name__ == "__main__":
    main()
