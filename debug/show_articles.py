"""
show_articles.py — 查看 data/news.db 最新 10 篇文章

執行方式：
    cd ~/Desktop/stock_sentiment
    python3 debug/show_articles.py
"""

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent.parent))

from models.db import get_connection, fetch_articles

DB_PATH = Path(__file__).parent.parent / "data" / "news.db"

COL_WIDTHS = {"#": 3, "source": 10, "published_at": 19, "title": 46}
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


def main():
    if not DB_PATH.exists():
        print(f"找不到資料庫：{DB_PATH}")
        print("請先執行：python3 pipeline/save_cnyes_to_db.py")
        return

    conn = get_connection(DB_PATH)
    rows = fetch_articles(conn, limit=10)
    conn.close()

    if not rows:
        print("資料庫是空的，尚無文章。")
        return

    print(f"\n最新 {len(rows)} 篇文章（{DB_PATH.name}）\n")
    print(DIVIDER)
    print_row("#", "source", "published_at", "title")
    print(DIVIDER)
    for i, row in enumerate(rows, 1):
        print_row(i, row["source"], row["published_at"][:19], row["title"])
    print(DIVIDER)
    print()


if __name__ == "__main__":
    main()
