"""
analyze_sentiment.py — 批次對未分析文章執行情緒分析

執行方式：
    cd ~/Desktop/stock_sentiment
    python3 pipeline/analyze_sentiment.py                      # Claude API 正常模式
    python3 pipeline/analyze_sentiment.py --dry-run            # 只分析 1 篇，不寫 DB
    python3 pipeline/analyze_sentiment.py --mock               # Mock 模式，不呼叫 API
    python3 pipeline/analyze_sentiment.py --mock --limit 5     # Mock 模式，指定篇數

模式說明：
    （預設）  使用 Claude API 分析，需要 ANTHROPIC_API_KEY
    --dry-run 只分析 1 篇並印出結果，不寫回 DB（仍呼叫 Claude API）
    --mock    不呼叫 Claude API，以關鍵字規則產生模擬結果並寫回 DB
              適用於 Demo / API credit 不足時

可調整常數：
    BATCH_LIMIT   : 非 --mock 模式的預設批次上限
    REQUEST_DELAY : Claude API 每篇之間等待秒數
"""

import json
import sys
import time
from pathlib import Path

# Python 3.9 在 stdout 被 pipe / 重導向時 encoding 會退回 ASCII，
# 強制設為 UTF-8 讓中文 print 在任何環境下都不炸。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent.parent))

from analysis.mock_sentiment import mock_analyze
from analysis.sentiment import SentimentAnalyzer
from models.db import (
    create_tables, fetch_unanalyzed, fetch_keywords_missing,
    get_connection, update_sentiment, update_keywords,
)

DB_PATH = Path(__file__).parent.parent / "data" / "news.db"

BATCH_LIMIT = 20
REQUEST_DELAY = 1.5


def _parse_args() -> tuple:
    """回傳 (dry_run, mock, keywords_only, limit)。"""
    args = sys.argv[1:]
    dry_run       = "--dry-run" in args
    mock          = "--mock" in args
    keywords_only = "--keywords-only" in args   # 只補 keywords，不覆蓋 sentiment

    limit = BATCH_LIMIT
    if "--limit" in args:
        idx = args.index("--limit")
        try:
            limit = int(args[idx + 1])
        except (IndexError, ValueError):
            print("[錯誤] --limit 後面必須接整數，例如 --limit 5")
            sys.exit(1)
    elif dry_run:
        limit = 1  # --dry-run 預設只分析 1 篇

    return dry_run, mock, keywords_only, limit


def main(
    dry_run: bool = False,
    mock: bool = False,
    keywords_only: bool = False,
    limit: int = BATCH_LIMIT,
) -> None:
    if not DB_PATH.exists():
        print(f"[錯誤] 找不到資料庫：{DB_PATH}")
        print("請先執行：python3 pipeline/save_cnyes_to_db.py")
        sys.exit(1)

    conn = get_connection(DB_PATH)
    create_tables(conn)

    # ── 模式選擇 ────────────────────────────────────────────────
    if keywords_only:
        # 只補 keywords：找已有 sentiment 但 keywords 為空的文章
        rows = fetch_keywords_missing(conn, limit=limit)
        mode_label = "[KEYWORDS-ONLY] "
    else:
        rows = fetch_unanalyzed(conn, limit=limit)
        mode_label = "[MOCK] " if mock else ("[DRY-RUN] " if dry_run else "")

    if not rows:
        if keywords_only:
            print("所有已分析文章都已有 keywords，無需補寫。")
        else:
            print("沒有待分析的文章（所有文章皆已有情緒標籤）。")
        conn.close()
        return

    print(f"\n{mode_label}共找到 {len(rows)} 篇文章，開始處理...\n")

    # Claude API 模式才初始化 analyzer（keywords_only 不需要 API）
    analyzer = None
    if not mock and not keywords_only:
        try:
            analyzer = SentimentAnalyzer()
        except EnvironmentError as e:
            print(e)
            conn.close()
            sys.exit(1)

    succeeded = 0
    failed = 0

    for i, row in enumerate(rows, 1):
        article_id: int = row["id"]
        title: str = row["title"]
        content = row["content"]

        try:
            stock_codes: list[str] = json.loads(row["stock_codes"] or "[]")
        except (json.JSONDecodeError, TypeError):
            stock_codes = []

        print(f"[{i}/{len(rows)}] {title[:50]}{'…' if len(title) > 50 else ''}")

        try:
            if keywords_only:
                # 只需要 mock_analyze 產生 keywords，不覆蓋 sentiment/score
                result = mock_analyze(title=title, content=content, stock_codes=stock_codes)
                kw_preview = ", ".join(result.keywords[:3])
                print(f"         → keywords: [{kw_preview}]")
                if not dry_run:
                    update_keywords(conn, article_id=article_id, keywords=result.keywords)
            elif mock:
                result = mock_analyze(title=title, content=content, stock_codes=stock_codes)
                score_label = f"{result.impact_score:.0f}/10"
                kw_preview  = ", ".join(result.keywords[:3])
                print(f"         → {result.sentiment}  {score_label}  [{kw_preview}]")
                if not dry_run:
                    update_sentiment(
                        conn, article_id=article_id,
                        sentiment=result.sentiment,
                        impact_score=result.impact_score,
                        reason=result.reason,
                        keywords=result.keywords,
                    )
            else:
                result = analyzer.analyze(title=title, content=content, stock_codes=stock_codes)  # type: ignore[union-attr]
                score_label    = f"{result.impact_score:.0f}/10"
                reason_preview = result.reason[:60] + ("…" if len(result.reason) > 60 else "")
                kw_preview     = ", ".join(result.keywords[:3])
                print(f"         → {result.sentiment}  {score_label}  [{kw_preview}]  {reason_preview}")
                if dry_run:
                    print("\n[DRY-RUN] 結果不寫入資料庫。")
                else:
                    update_sentiment(
                        conn, article_id=article_id,
                        sentiment=result.sentiment,
                        impact_score=result.impact_score,
                        reason=result.reason,
                        keywords=result.keywords,
                    )

            succeeded += 1

        except Exception as e:
            print(f"         → [錯誤] {e}")
            failed += 1

        if i < len(rows) and not mock and not keywords_only:
            time.sleep(REQUEST_DELAY)

    conn.close()

    print()
    if dry_run:
        print("── DRY-RUN 結果（未寫入 DB）─────────")
    elif keywords_only:
        print("── KEYWORDS-ONLY 補寫完成 ────────────")
    elif mock:
        print("── MOCK 分析結果（已寫入 DB）─────────")
    else:
        print("── 分析結果（已寫入 DB）──────────────")
    print(f"  成功  : {succeeded} 篇")
    print(f"  失敗  : {failed} 篇")
    if not dry_run:
        print(f"  DB 位置: {DB_PATH}")
    print("──────────────────────────────────────")


if __name__ == "__main__":
    _dry_run, _mock, _keywords_only, _limit = _parse_args()
    main(dry_run=_dry_run, mock=_mock, keywords_only=_keywords_only, limit=_limit)
