"""
show_analyzed_articles.py — 查看最新 10 篇已分析文章的情緒結果

執行方式：
    cd ~/Desktop/stock_sentiment
    python3 debug/show_analyzed_articles.py
"""

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent.parent))

from models.db import get_connection

DB_PATH = Path(__file__).parent.parent / "data" / "news.db"

# 欄寬設定（中文字佔 2 格）
COL_WIDTHS = {"#": 3, "sentiment": 6, "score": 5, "title": 38, "reason": 36}
DIVIDER = "-" * (sum(COL_WIDTHS.values()) + len(COL_WIDTHS) * 3 + 1)


def fmt(text: str, width: int) -> str:
    """截斷或補空白，處理中文字（每個中文字佔 2 格）。"""
    result, count = "", 0
    for ch in str(text):
        w = 2 if ord(ch) > 127 else 1
        if count + w > width:
            result += "…" if count + 1 <= width else ""
            break
        result += ch
        count += w
    return result.ljust(width - max(0, count - len(result)))


def print_row(*cols):
    widths = list(COL_WIDTHS.values())
    cells = [fmt(str(v), widths[i]) for i, v in enumerate(cols)]
    print("| " + " | ".join(cells) + " |")


SENTIMENT_LABEL = {"正面": "正面 ▲", "負面": "負面 ▼", "中立": "中立 ─"}


def main():
    if not DB_PATH.exists():
        print(f"找不到資料庫：{DB_PATH}")
        print("請先執行：python3 pipeline/save_cnyes_to_db.py")
        return

    conn = get_connection(DB_PATH)
    rows = conn.execute(
        """
        SELECT title, sentiment, impact_score, reason
        FROM   articles
        WHERE  sentiment IS NOT NULL
        ORDER  BY published_at DESC
        LIMIT  10
        """
    ).fetchall()
    conn.close()

    if not rows:
        print("\n尚無已分析的文章。")
        print("請先執行情緒分析：")
        print("  python3 pipeline/analyze_sentiment.py --dry-run  # 測試 1 篇，不寫入 DB")
        print("  python3 pipeline/analyze_sentiment.py            # 正式分析並寫入 DB")
        return

    print(f"\n最新 {len(rows)} 篇已分析文章（{DB_PATH.name}）\n")
    print(DIVIDER)
    print_row("#", "情緒", "分數", "標題", "判斷理由")
    print(DIVIDER)
    for i, row in enumerate(rows, 1):
        label = SENTIMENT_LABEL.get(row["sentiment"], row["sentiment"])
        score = f"{row['impact_score']:.0f}/10" if row["impact_score"] is not None else "—"
        print_row(i, label, score, row["title"], row["reason"] or "")
    print(DIVIDER)
    print()


if __name__ == "__main__":
    main()
