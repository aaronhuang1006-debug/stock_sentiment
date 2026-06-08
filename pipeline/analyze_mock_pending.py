"""
analyze_mock_pending.py — rule-based 補分析所有 pending articles.

執行方式：
    cd ~/Desktop/stock_sentiment
    python3 pipeline/analyze_mock_pending.py

功能：
  - 查詢 sentiment IS NULL OR impact_score IS NULL 的文章
  - 使用 analysis/mock_sentiment.py 的 Rule-Based Analyzer
  - 寫回 sentiment / impact_score / reason / keywords
  - 不重複分析已完整分析文章
"""

import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from analysis.mock_sentiment import mock_analyze
from models.db import create_tables, get_connection, update_sentiment

DB_PATH = ROOT / "data" / "news.db"


def fetch_mock_pending(conn) -> list:
    return conn.execute(
        """
        SELECT *
        FROM articles
        WHERE sentiment IS NULL OR impact_score IS NULL
        ORDER BY published_at DESC
        """
    ).fetchall()


def main() -> None:
    conn = get_connection(DB_PATH)
    create_tables(conn)

    rows = fetch_mock_pending(conn)
    total = len(rows)
    skipped = conn.execute(
        "SELECT COUNT(*) FROM articles WHERE sentiment IS NOT NULL AND impact_score IS NOT NULL"
    ).fetchone()[0]

    print("── Rule-Based Pending Analysis ─────────────")
    print(f"待分析 : {total} 篇")
    print(f"跳過已完整分析 : {skipped} 篇")

    if total == 0:
        print("\n✅ 沒有待分析文章，所有文章均已完成分析。")
        conn.close()
        return

    succeeded = failed = 0
    for i, row in enumerate(rows, 1):
        title = row["title"]
        content = row["content"]
        try:
            stock_codes = json.loads(row["stock_codes"] or "[]")
        except (json.JSONDecodeError, TypeError):
            stock_codes = []

        print(f"[{i}/{total}] {title[:50]}{'…' if len(title) > 50 else ''}")
        try:
            result = mock_analyze(title=title, content=content, stock_codes=stock_codes)
            update_sentiment(
                conn,
                article_id=row["id"],
                sentiment=result.sentiment,
                impact_score=result.impact_score,
                reason=result.reason,
                keywords=result.keywords,
            )
            print(
                f"         → {result.sentiment} {result.impact_score:.1f}/10 "
                f"[{', '.join(result.keywords[:3])}]"
            )
            succeeded += 1
        except Exception as e:
            print(f"         → [錯誤] {e}")
            failed += 1

    remaining = conn.execute(
        "SELECT COUNT(*) FROM articles WHERE sentiment IS NULL OR impact_score IS NULL"
    ).fetchone()[0]
    conn.close()

    print()
    print("── Rule-Based 分析完成 ───────────────")
    print(f"  成功 : {succeeded} 篇")
    print(f"  失敗 : {failed} 篇")
    print(f"  剩餘 pending : {remaining} 篇")
    print(f"  DB 位置: {DB_PATH}")
    print("──────────────────────────────────────")


if __name__ == "__main__":
    main()
