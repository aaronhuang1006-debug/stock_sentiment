"""
app.py — 台股新聞 AI 分析平台（Streamlit）

執行方式：
    cd ~/Desktop/stock_sentiment
    streamlit run web/app.py
"""

import json
import re
import sqlite3
import sys
from html import escape
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

# ── 載入 .env（本機開發）；Streamlit Cloud 上 .env 不存在，靜默略過 ──
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv()
except ImportError:
    pass

from models.price import get_validation_df
from models.db import create_tables

DB_PATH = Path(__file__).parent.parent / "data" / "news.db"

# ─────────────────────────────────────────────────────────────
# 頁面設定
# ─────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="台股新聞 AI 分析平台",
    page_icon="📈",
    layout="wide",
)

# ─────────────────────────────────────────────────────────────
# 登入 Gate — 未登入時只顯示登入頁，阻止後續渲染
# ─────────────────────────────────────────────────────────────
if "username" not in st.session_state:
    from web.login_page import render_login_page
    render_login_page()
    st.stop()

# ─────────────────────────────────────────────────────────────
# 全域樣式
# ─────────────────────────────────────────────────────────────

st.markdown("""
<style>
/* ── reset & base ── */
html, body, [data-testid="stAppViewContainer"] {
    font-family: "Inter", "SF Pro Text", "Helvetica Neue", Arial, sans-serif;
    background: #f8f9fa;
}
[data-testid="stMain"] { background: #f8f9fa; }
div[data-testid="stVerticalBlock"] { gap: 0 !important; }

/* ── 頁首 ── */
.hdr            { padding: 1rem 0 0.9rem; border-bottom: 1.5px solid #e2e4e9; margin-bottom: 1rem; }
.hdr-title      { font-size: 1.55rem; font-weight: 700; color: #0d0f14; letter-spacing: -.03em; }
.hdr-sub        { font-size: 0.8rem; color: #8a8f9e; margin-top: .2rem; }
.hdr-time       { font-size: 0.72rem; color: #b0b5c3; margin-top: .12rem; }

/* ── Hero 卡片 ── */
.hero-card {
    background: #f0f4ff;
    border: 1px solid #c7d4f5;
    border-left: 4px solid #2563eb;
    border-radius: 8px;
    padding: 1.1rem 1.35rem;
    margin-bottom: 1rem;
    box-shadow: 0 2px 8px rgba(37,99,235,.08);
}
.hero-eyebrow   { font-size: .68rem; font-weight: 700; color: #2563eb;
                  text-transform: uppercase; letter-spacing: .08em; margin-bottom: .4rem; }
.hero-title     { font-size: 1.2rem; font-weight: 700; color: #0d0f14; line-height: 1.45;
                  margin-bottom: .55rem; }
.hero-title a   { color: inherit; text-decoration: none; }
.hero-title a:hover { text-decoration: underline; }
.hero-meta      { display: flex; gap: 8px; flex-wrap: wrap; align-items: center;
                  margin-bottom: .6rem; }
.hero-reason    { font-size: .83rem; color: #3d4460; line-height: 1.6;
                  border-top: 1px solid #d1daf5; padding-top: .6rem; margin-top: .1rem; }
.reason-box {
    background: #f8fafd;
    border: 1px solid #eaecf4;
    border-left: 2px solid #c7d2e8;
    border-radius: 6px;
    padding: .5rem .75rem;
    margin: .45rem 0;
}
.reason-title {
    font-size: .63rem;
    font-weight: 700;
    color: #94a3b8;
    text-transform: uppercase;
    letter-spacing: .07em;
    margin-bottom: .28rem;
}
.reason-list {
    margin: 0;
    padding-left: .9rem;
    color: #475569;
    font-size: .76rem;
    line-height: 1.5;
}
.reason-list li { margin-bottom: .15rem; }

/* ── Metric 卡片 ── */
.mc {
    background: #ffffff;
    border: 1px solid #e2e4e9;
    border-radius: 8px;
    padding: .9rem 1.1rem .8rem;
    box-shadow: 0 1px 3px rgba(0,0,0,.05);
}
.mc-label { font-size: .68rem; font-weight: 700; color: #8a8f9e;
            text-transform: uppercase; letter-spacing: .07em; }
.mc-value { font-size: 2.1rem; font-weight: 800; color: #0d0f14;
            line-height: 1.15; margin: .3rem 0 .18rem; letter-spacing: -.03em; }
.mc-sub   { font-size: .74rem; color: #b0b5c3; line-height: 1.4; }
.mc-source-list { display: grid; gap: .35rem; margin: .45rem 0 .2rem; }
.mc-source-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: .55rem;
    min-width: 0;
}
.mc-source-name {
    font-size: .82rem;
    font-weight: 650;
    color: #374151;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
.mc-source-count {
    font-size: .9rem;
    font-weight: 800;
    color: #0d0f14;
    font-variant-numeric: tabular-nums;
}

/* ── Section title ── */
.sec-title { font-size: .7rem; font-weight: 700; color: #8a8f9e;
             text-transform: uppercase; letter-spacing: .08em;
             margin: 1.1rem 0 .65rem; }

/* ── Top 5 卡片 ── */
.t5-card {
    background: #ffffff;
    border: 1px solid #e8eaef;
    border-left: 3px solid #cbd5e1;
    border-radius: 8px;
    padding: .7rem 1rem;
    margin-bottom: .4rem;
    display: flex;
    align-items: center;
    gap: 12px;
    box-shadow: 0 1px 2px rgba(0,0,0,.03);
}
.t5-card-high { border-left: 3px solid #ef4444; }
.t5-card-mid  { border-left: 3px solid #f59e0b; }
.t5-card-low  { border-left: 3px solid #cbd5e1; }
.t5-rank {
    font-size: 1rem; font-weight: 900; color: #d1d5db;
    min-width: 28px; text-align: center; flex-shrink: 0;
    font-variant-numeric: tabular-nums;
}
.t5-card-high .t5-rank { color: #fca5a5; }
.t5-card-mid  .t5-rank { color: #fcd34d; }
.t5-body  { flex: 1; min-width: 0; }
.t5-ttl   { font-size: .88rem; font-weight: 600; color: #0d0f14;
            line-height: 1.4; margin-bottom: .35rem; }
.t5-ttl a { color: inherit; text-decoration: none; }
.t5-ttl a:hover { text-decoration: underline; background: rgba(0,0,0,.04);
                  border-radius: 2px; padding: 0 2px; }
.t5-chips { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.t5-right { display: flex; flex-direction: column; align-items: flex-end;
            gap: 4px; flex-shrink: 0; padding-top: 1px; min-width: 100px; }

/* ── Chip / Badge / Pill ── */
.badge  { display:inline-block; padding:1px 7px; border-radius:3px;
          font-size:.68rem; font-weight:600; letter-spacing:.02em; white-space:nowrap; }
.b-cnyes    { background:#fef2ee; color:#c94a1e; border:1px solid #f5c5b2; }
.b-yahoo    { background:#f0eafe; color:#5b21b6; border:1px solid #c4b5fd; }
.b-unknown  { background:#f3f4f6; color:#374151; border:1px solid #d1d5db; }

.chip { display:inline-block; padding:1px 8px; border-radius:99px;
        font-size:.68rem; font-weight:600; white-space:nowrap; }
.c-pos  { background:#ecfdf5; color:#059669; border:1px solid #a7f3d0; }
.c-neg  { background:#fff1f2; color:#e11d48; border:1px solid #fecdd3; }
.c-neu  { background:#fefce8; color:#a16207; border:1px solid #fef08a; }
.c-none { background:#f9fafb; color:#9ca3af; border:1px solid #e5e7eb; }

.spill { display:inline-block; padding:2px 8px; border-radius:4px;
         font-size:.72rem; font-weight:700; white-space:nowrap; }
.s-high { background:#fef2f2; color:#b91c1c; border:1px solid #fecaca; }
.s-mid  { background:#fff7ed; color:#c2410c; border:1px solid #fed7aa; }
.s-low  { background:#f9fafb; color:#6b7280; border:1px solid #e5e7eb; }
.s-none { background:#f9fafb; color:#d1d5db; border:1px solid #f3f4f6; }

/* ── 新聞卡片（ncard：related news；news-card：主列表，統一白底+左色條）── */
.ncard, .news-card {
    background: #ffffff;
    border: 1px solid #e8eaef;
    border-left: 3px solid #cbd5e1;
    border-radius: 8px;
    padding: .8rem 1rem .75rem;
    margin-bottom: .45rem;
    box-shadow: 0 1px 2px rgba(0,0,0,.03);
}
.ncard:hover, .news-card:hover { border-color: #b0bcd4; box-shadow: 0 2px 6px rgba(0,0,0,.06); }
.nmeta  { display:flex; gap:6px; flex-wrap:wrap; align-items:center; margin-bottom:.35rem; }
.ntime  { font-size:.71rem; color:#b0b5c3; }
.nttl   { font-size:.97rem; font-weight:600; color:#0d0f14; line-height:1.5; margin:0 0 .15rem; }
.nttl a { color:inherit; text-decoration:none; }
.nttl a:hover { color:#2563eb; text-decoration:underline; }
.nstock { font-size:.69rem; color:#6b7280; background:#f3f4f6; border-radius:3px; padding:1px 5px; }
/* Left-border accent by sentiment */
.news-card-positive { border-left-color: #10b981; }
.news-card-negative { border-left-color: #e11d48; }
.news-card-neutral  { border-left-color: #f59e0b; }
.news-card-pending  { border-left-color: #94a3b8; }
.news-card-top {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 12px;
}
.news-card-title { flex: 1; min-width: 0; }
.news-card-badges { display:flex; gap:6px; flex-wrap:wrap; align-items:center; margin-top:.4rem; }
.rel-badge {
    display:inline-flex; align-items:center; height:20px; padding:0 8px;
    border-radius:999px; font-size:.68rem; font-weight:700;
    color:#075985; background:#e0f2fe; border:1px solid #bae6fd;
}
.rel-badge-high { color:#7f1d1d; background:#fee2e2; border-color:#fecaca; }
.stock-chip {
    display:inline-flex; align-items:center; height:20px; padding:0 8px;
    border-radius:999px; font-size:.67rem; font-weight:650;
    color:#334155; background:#f1f5f9; border:1px solid #dbe3ee;
}
.stock-row { display:flex; gap:6px; flex-wrap:wrap; margin-top:.45rem; }
/* High impact: subtle outline badge only, no card re-coloring */
.hi-badge {
    display: inline-block;
    padding: 1px 7px;
    border-radius: 4px;
    background: #fff1f2;
    color: #b91c1c;
    border: 1px solid #fecaca;
    font-size: .67rem;
    font-weight: 700;
    white-space: nowrap;
}
.pending-badge {
    display: inline-block;
    padding: 1px 7px;
    border-radius: 4px;
    background: #f8fafc;
    color: #64748b;
    border: 1px solid #e2e8f0;
    font-size: .67rem;
    font-weight: 600;
    white-space: nowrap;
}

/* ── Sidebar ── */
[data-testid="stSidebar"] { background:#ffffff; border-right:1px solid #e2e4e9; }
[data-testid="stSidebar"] { min-width: 260px; max-width: 310px; }
[data-testid="stSidebar"] > div:first-child { padding-left: 1rem; padding-right: 1rem; }
.sb-title { font-size:.68rem; font-weight:700; color:#8a8f9e;
            text-transform:uppercase; letter-spacing:.08em; margin-bottom:.6rem; }

/* ── Insight bar ── */
.insight-bar {
    background: #ffffff;
    border: 1px solid #e2e4e9;
    border-left: 3px solid #2563eb;
    border-radius: 6px;
    padding: .6rem 1rem;
    margin: .6rem 0 .9rem;
    font-size: .82rem;
    color: #374151;
    line-height: 1.55;
    box-shadow: 0 1px 2px rgba(0,0,0,.04);
}
.insight-bar strong { color: #0d0f14; }

/* ── High-impact alert ── */
.alert-high {
    background: #fff7ed;
    border: 1px solid #fed7aa;
    border-left: 3px solid #f97316;
    border-radius: 6px;
    padding: .55rem 1rem;
    margin-bottom: .75rem;
    font-size: .82rem;
    color: #9a3412;
    font-weight: 500;
}

/* ── Empty state ── */
.empty-state {
    text-align: center;
    padding: 3rem 1rem;
    color: #8a8f9e;
}
.empty-state-icon { font-size: 2.2rem; margin-bottom: .75rem; }
.empty-state-title { font-size: 1rem; font-weight: 600; color: #374151; margin-bottom: .35rem; }
.empty-state-sub   { font-size: .82rem; }

/* ── Error state ── */
.error-state {
    background: #fff1f2;
    border: 1px solid #fecdd3;
    border-radius: 8px;
    padding: 1.5rem;
    text-align: center;
    color: #9f1239;
}
.error-state-title { font-size: 1rem; font-weight: 700; margin-bottom: .4rem; }
.error-state-sub   { font-size: .82rem; color: #be123c; }

/* ── Mobile：metric 換行不爆版 ── */
@media (max-width: 900px) {
    .mc-value { font-size: 1.5rem; }
    .t5-card  { flex-wrap: wrap; }
    .t5-right { min-width: auto; }
}

/* ── Pipeline 狀態列（sidebar 用）── */
.pipe-status {
    background: #f8f9fa;
    border: 1px solid #e2e4e9;
    border-radius: 6px;
    padding: .55rem .8rem;
    margin-top: .5rem;
    font-size: .74rem;
    color: #374151;
    line-height: 1.8;
}
.pipe-status-title {
    font-size: .65rem; font-weight: 700; color: #8a8f9e;
    text-transform: uppercase; letter-spacing: .07em;
    margin-bottom: .35rem;
}
.pipe-dot-ok  { color: #059669; font-size: .7rem; }
.pipe-dot-err { color: #e11d48; font-size: .7rem; }
.pipe-dot-na  { color: #d1d5db; font-size: .7rem; }

/* 緊縮 streamlit 內建間距，同時解除寬螢幕最大寬度限制 */
.block-container {
    max-width: none !important;
    width: 100% !important;
    padding: 1rem 2rem 2rem !important;
}
[data-testid="stMainBlockContainer"] { max-width: none !important; }
[data-testid="column"] > div { width: 100%; }
[data-testid="stExpander"] { border:none !important; box-shadow:none; }

@media (max-width: 900px) {
    .block-container { padding-left: 1rem !important; padding-right: 1rem !important; }
}

/* ── Market Drivers 區塊 ── */
.md-section { margin: .6rem 0 .4rem; }
.md-card {
    background: #fff;
    border: 1px solid #e2e4e9;
    border-radius: 8px;
    padding: .7rem .9rem;
    margin-bottom: .45rem;
    display: flex; align-items: center; gap: .6rem;
}
.md-card:hover { border-color: #6366f1; box-shadow: 0 2px 8px rgba(99,102,241,.1); }
.md-rank  { font-size: 1rem; font-weight: 800; color: #c7d2fe; min-width: 1.5rem; }
.md-kw    { font-size: .95rem; font-weight: 700; color: #1e293b; flex: 1; }
.md-meta  { font-size: .72rem; color: #94a3b8; }
.md-score { font-size: .8rem; font-weight: 700; color: #6366f1;
            background: #eef2ff; border-radius: 4px; padding: 2px 7px; }
.md-pos   { border-left: 3px solid #059669; }
.md-neg   { border-left: 3px solid #e11d48; }
.md-mix   { border-left: 3px solid #d97706; }

/* ── Keyword chips（News Card + High Impact）── */
.kw-chip {
    display: inline-block;
    background: #f1f5f9;
    border: 1px solid #e2e8f0;
    border-radius: 4px;
    font-size: .68rem;
    color: #475569;
    padding: 1px 6px;
    margin: 2px 3px 2px 0;
}
.kw-cnt {
    display: inline-block;
    background: #6366f1;
    color: #fff;
    border-radius: 9px;
    font-size: .6rem;
    padding: 0 4px;
    margin-left: 2px;
}
.kw-row { margin-top: .3rem; line-height: 1.8; }

/* ── High Impact Keywords chip grid ── */
.hi-kw-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
    gap: .45rem;
    margin-top: .5rem;
}
.hi-kw-card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: .5rem .75rem;
    box-shadow: 0 1px 2px rgba(0,0,0,.03);
    transition: box-shadow .15s, border-color .15s;
}
.hi-kw-card:hover {
    box-shadow: 0 3px 8px rgba(0,0,0,.08);
    border-color: #c7d2e8;
}
.hi-kw-name {
    font-size: .78rem;
    font-weight: 600;
    color: #1e293b;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.hi-kw-meta {
    font-size: .65rem;
    color: #94a3b8;
    margin-top: .15rem;
}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────
# 常數
# ─────────────────────────────────────────────────────────────

SOURCE_META = {
    "cnyes":    {"label": "鉅亨網",      "css": "b-cnyes"},
    "yahoo_tw": {"label": "Yahoo 股市", "css": "b-yahoo"},
}
SENTI_MAP = {
    "正面": ("c-pos", "正面"),
    "負面": ("c-neg", "負面"),
    "中立": ("c-neu", "中立"),
}

# ─────────────────────────────────────────────────────────────
# 資料載入（邏輯不變）
# ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_pipeline_status() -> dict:
    """
    載入最近一次 pipeline 執行紀錄與資料庫總筆數。
    回傳 dict，key: ran_at / mode / inserted / analyzed / duration_sec / db_total
    若無紀錄，各欄位為 None。
    """
    if not DB_PATH.exists():
        return {}
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # 確保所有表都存在（含 articles / pipeline_runs）
    create_tables(conn)
    row = conn.execute(
        "SELECT * FROM pipeline_runs ORDER BY ran_at DESC LIMIT 1"
    ).fetchone()
    try:
        total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    except Exception:
        total = 0
    conn.close()
    if row is None:
        return {"db_total": total}
    return {
        "ran_at":       row["ran_at"],
        "mode":         row["mode"],
        "inserted":     row["inserted"],
        "analyzed":     row["analyzed"],
        "duration_sec": row["duration_sec"],
        "error":        row["error"],
        "db_total":     total,
    }


@st.cache_data(ttl=60)
def load_articles() -> pd.DataFrame:
    if not DB_PATH.exists():
        return pd.DataFrame()
    conn = sqlite3.connect(DB_PATH)
    create_tables(conn)
    df = pd.read_sql_query(
        """SELECT id, source, title, url, published_at,
                  sentiment, impact_score, reason, stock_codes,
                  COALESCE(keywords, '[]') AS keywords,
                  relevance_score,
                  COALESCE(affected_stocks, '[]') AS affected_stocks,
                  analysis_method
           FROM   articles ORDER BY published_at DESC""",
        conn,
    )
    conn.close()

    def parse_codes(raw):
        try:
            codes = json.loads(raw or "[]")
            return ", ".join(codes) if codes else ""
        except Exception:
            return ""

    def parse_keywords(raw):
        """安全解析 keywords JSON，失敗一律回傳空列表。"""
        try:
            kws = json.loads(raw or "[]")
            return kws if isinstance(kws, list) else []
        except Exception:
            return []

    def parse_stocks(raw):
        try:
            stocks = json.loads(raw or "[]")
            return stocks if isinstance(stocks, list) else []
        except Exception:
            return []

    df["stock_codes_str"] = df["stock_codes"].apply(parse_codes)
    df["keywords_list"]   = df["keywords"].apply(parse_keywords)
    df["affected_stocks_list"] = df["affected_stocks"].apply(parse_stocks)
    df["published_at"]    = pd.to_datetime(df["published_at"], errors="coerce")
    return df

@st.cache_data(ttl=60)
def load_validation_returns() -> pd.DataFrame:
    if not DB_PATH.exists():
        return pd.DataFrame()
    conn = sqlite3.connect(DB_PATH)
    try:
        return get_validation_df(conn)
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────
# Keywords 聚合工具
# ─────────────────────────────────────────────────────────────

def build_keyword_stats(df: "pd.DataFrame", top_n: int = 20) -> "pd.DataFrame":
    """
    從 df["keywords_list"] 聚合關鍵字頻率 + 加權 impact_score。
    回傳 DataFrame，columns: keyword, count, avg_impact, driver_score, sentiment_mix
    sentiment_mix: 'positive' / 'negative' / 'mixed'（依多數情緒決定顏色）
    容錯：keywords_list 欄不存在或為空時回傳空 DataFrame。
    """
    if "keywords_list" not in df.columns or df.empty:
        return pd.DataFrame()

    records: dict = {}   # keyword -> {count, impact_sum, pos, neg}
    for _, row in df.iterrows():
        kws = row.get("keywords_list", [])
        if not isinstance(kws, list) or not kws:
            continue
        score   = float(row["impact_score"]) if pd.notna(row.get("impact_score")) else 5.0
        senti   = str(row.get("sentiment", ""))
        for kw in kws:
            if not kw:
                continue
            if kw not in records:
                records[kw] = {"count": 0, "impact_sum": 0.0, "pos": 0, "neg": 0}
            records[kw]["count"]      += 1
            records[kw]["impact_sum"] += score
            if senti == "正面":
                records[kw]["pos"] += 1
            elif senti == "負面":
                records[kw]["neg"] += 1

    if not records:
        return pd.DataFrame()

    rows = []
    for kw, v in records.items():
        cnt        = v["count"]
        avg_impact = v["impact_sum"] / cnt if cnt else 0
        driver     = round(cnt * avg_impact, 2)   # 驅動力分數
        if v["pos"] > v["neg"]:
            mix = "positive"
        elif v["neg"] > v["pos"]:
            mix = "negative"
        else:
            mix = "mixed"
        rows.append({
            "keyword":      kw,
            "count":        cnt,
            "avg_impact":   round(avg_impact, 1),
            "driver_score": driver,
            "sentiment_mix": mix,
        })

    result = pd.DataFrame(rows).sort_values("driver_score", ascending=False)
    return result.head(top_n).reset_index(drop=True)


def kw_chip(word: str, count: int = 0) -> str:
    """把關鍵字 + 出現次數渲染成 HTML chip。"""
    cnt_badge = f' <span class="kw-cnt">{count}</span>' if count else ""
    return f'<span class="kw-chip">{word}{cnt_badge}</span>'


# ─────────────────────────────────────────────────────────────
# HTML 產生器（純表現層）
# ─────────────────────────────────────────────────────────────

def src_badge(source: str) -> str:
    m = SOURCE_META.get(source, {"label": source, "css": "b-unknown"})
    return f'<span class="badge {m["css"]}">{m["label"]}</span>'

def senti_chip(val) -> str:
    if pd.isna(val):
        return '<span class="chip c-none">未分析</span>'
    css, label = SENTI_MAP.get(str(val), ("c-none", str(val)))
    return f'<span class="chip {css}">{label}</span>'

def score_pill(val) -> str:
    if pd.isna(val):
        return '<span class="spill s-none">—</span>'
    v = float(val)
    if v >= 8:   css, tier = "s-high", "高影響"
    elif v >= 5: css, tier = "s-mid",  "中影響"
    else:        css, tier = "s-low",  "低影響"
    return f'<span class="spill {css}">{v:.0f}/10 · {tier}</span>'

def news_card_class(row) -> str:
    sentiment = row.get("sentiment")
    if pd.isna(sentiment):
        return "news-card news-card-pending"
    if str(sentiment) == "正面":
        return "news-card news-card-positive"
    if str(sentiment) == "負面":
        return "news-card news-card-negative"
    return "news-card news-card-neutral"

def high_impact_badge(val) -> str:
    if pd.notna(val) and float(val) >= 8:
        return '<span class="hi-badge">High Impact</span>'
    return ""

def relevance_badge(val) -> str:
    if pd.isna(val):
        return ""
    v = float(val)
    css = "rel-badge rel-badge-high" if v >= 70 else "rel-badge"
    return f'<span class="{css}">Relevance {v:.0f}</span>'

def affected_stock_chips(stocks: list) -> str:
    if not isinstance(stocks, list) or not stocks:
        return ""
    chips = []
    for stock in stocks[:6]:
        if not isinstance(stock, dict):
            continue
        symbol = escape(str(stock.get("symbol") or ""))
        name = escape(str(stock.get("name") or ""))
        label = f"{symbol} {name}".strip()
        if label:
            chips.append(f'<span class="stock-chip">{label}</span>')
    return f'<div class="stock-row">{"".join(chips)}</div>' if chips else ""

def pending_badge(is_pending: bool) -> str:
    return '<span class="pending-badge">Pending analysis</span>' if is_pending else ""

def source_metric_rows(src_counts: "pd.Series") -> str:
    rows = []
    for source, count in src_counts.items():
        label = SOURCE_META.get(source, {}).get("label", source)
        rows.append(
            '<div class="mc-source-row">'
            f'<span class="mc-source-name">{label}</span>'
            f'<span class="mc-source-count">{count}</span>'
            '</div>'
        )
    return '<div class="mc-source-list">' + "".join(rows) + "</div>"

def related_articles_for_driver(df: "pd.DataFrame", keyword: str) -> "pd.DataFrame":
    if df.empty or "keywords_list" not in df.columns:
        return pd.DataFrame()
    mask = df["keywords_list"].apply(
        lambda kws: isinstance(kws, list) and keyword in kws
    )
    related = df[mask].copy()
    if related.empty:
        return related
    return related.sort_values(
        ["impact_score", "published_at"],
        ascending=[False, False],
        na_position="last",
    )

def driver_performance(related: "pd.DataFrame", validation_returns: "pd.DataFrame") -> dict:
    if related.empty or validation_returns.empty:
        return {}
    article_ids = set(related["id"].dropna().astype(int).tolist())
    if not article_ids or "article_id" not in validation_returns.columns:
        return {}
    matched = validation_returns[validation_returns["article_id"].isin(article_ids)]
    if matched.empty:
        return {}
    perf = {}
    for col in ["return_1d", "return_3d", "return_5d"]:
        if col in matched.columns:
            avg = matched[col].dropna().mean()
            if not pd.isna(avg):
                perf[col] = avg
    return perf

def fmt_pct(val) -> str:
    if val is None or pd.isna(val):
        return "—"
    return f"{float(val):+.2f}%"

def fmt_time(val) -> str:
    if pd.isna(val):
        return "—"
    try:
        return val.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(val)

def format_reason(reason: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(reason or "")).strip()
    if not cleaned:
        bullets = ["No analysis reason available"]
    else:
        raw_parts = re.split(
            r"(?:[。；;]|，|,|\b(?:because|due to|as)\b)",
            cleaned,
            flags=re.IGNORECASE,
        )
        parts = [p.strip(" ：:-") for p in raw_parts if p and p.strip(" ：:-")]
        if len(parts) <= 1 and len(cleaned) > 90:
            parts = [cleaned[i:i + 90] for i in range(0, len(cleaned), 90)]

        bullets = []
        for part in parts:
            item = part.strip()
            if not item:
                continue
            if len(item) > 90:
                item = item[:90].rstrip() + "..."
            bullets.append(item)
            if len(bullets) >= 5:
                break
        if not bullets:
            bullets = ["No analysis reason available"]

    bullet_html = "".join(f"<li>{escape(item)}</li>" for item in bullets)
    return (
        '<div class="reason-box">'
        '<div class="reason-title">AI Analysis</div>'
        f'<ul class="reason-list">{bullet_html}</ul>'
        '</div>'
    )

def format_pending_analysis() -> str:
    return (
        '<div class="reason-box">'
        '<div class="reason-title">AI Analysis</div>'
        '<ul class="reason-list"><li>Pending analysis</li></ul>'
        '</div>'
    )

def render_performance_metrics(perf: dict, title: str) -> None:
    st.markdown(f"**{title}**")
    if perf:
        perf_cols = st.columns(3)
        perf_cols[0].metric("Avg T+1", fmt_pct(perf.get("return_1d")))
        perf_cols[1].metric("Avg T+3", fmt_pct(perf.get("return_3d")))
        perf_cols[2].metric("Avg T+5", fmt_pct(perf.get("return_5d")))
    else:
        st.caption("Insufficient validation data")

def render_related_news(related: "pd.DataFrame", key_prefix: str, limit: int = 5) -> None:
    if related.empty:
        st.caption("No related news found.")
        return

    display_related = related.head(limit)
    total_related   = len(related)
    suffix = f" of {total_related}" if total_related > limit else ""
    st.caption(f"Showing top {len(display_related)}{suffix} related news · sorted by impact")

    for news_idx, (_, article) in enumerate(display_related.iterrows(), 1):
        news_title  = str(article.get("title") or "Untitled")
        article_url = str(article.get("url") or "").strip()
        title_html  = (
            f'<a href="{escape(article_url)}" target="_blank">{escape(news_title)}</a>'
            if article_url else escape(news_title)
        )
        source_label = SOURCE_META.get(article.get("source"), {}).get(
            "label", article.get("source", "—")
        )
        st.markdown(f"""
<div class="ncard">
  <div class="nmeta">
    <span class="badge b-unknown">{escape(str(source_label))}</span>
    {senti_chip(article.get('sentiment'))}
    {score_pill(article.get('impact_score'))}
    <span class="ntime">{fmt_time(article.get('published_at'))}</span>
  </div>
  <div class="nttl">{news_idx}. {title_html}</div>
</div>""", unsafe_allow_html=True)

def _build_insight(today_cnt: int, avg_score: float, pos_pct: float, neg_pct: float,
                   src_counts: "pd.Series", analyzed: int) -> str:
    avg_str = f"{avg_score:.1f}" if not pd.isna(avg_score) else "—"
    top_src = SOURCE_META.get(src_counts.index[0], {}).get("label", src_counts.index[0]) \
              if len(src_counts) else "—"
    if pd.isna(avg_score) or analyzed == 0:
        interp = "尚無足夠分析資料，建議先執行情緒分析。"
    elif avg_score >= 7:
        interp = "今日新聞以<strong>高影響</strong>事件為主，建議優先檢視 Top 5。"
    elif avg_score >= 5:
        if pos_pct > neg_pct + 10:
            interp = "整體情緒偏正面，市場訊號相對樂觀。"
        elif neg_pct > pos_pct + 10:
            interp = "整體情緒偏負面，請注意潛在風險。"
        else:
            interp = "新聞影響力中等，正負情緒大致平衡。"
    else:
        interp = "今日新聞影響力偏低，市場訊號較為平靜。"
    return (
        f"今日 <strong>{today_cnt}</strong> 篇新聞 ／ "
        f"已分析 <strong>{analyzed}</strong> 篇 ／ "
        f"平均影響力 <strong>{avg_str}/10</strong> ／ "
        f"主要來源：<strong>{top_src}</strong>　→　{interp}"
    )

def t5_card_css(val) -> str:
    if pd.isna(val): return "t5-card-low"
    v = float(val)
    if v >= 8:   return "t5-card-high"
    elif v >= 5: return "t5-card-mid"
    return "t5-card-low"


# ─────────────────────────────────────────────────────────────
# 載入資料 & 統計
# ─────────────────────────────────────────────────────────────

# ── 確保 DB 檔案與所有 tables 存在（空 DB 時建立，不影響有資料的 DB）──
try:
    _pre_conn = sqlite3.connect(DB_PATH)
    create_tables(_pre_conn)
    _pre_conn.close()
except Exception:
    pass

_load_error: str = ""
try:
    df_all = load_articles()
except Exception as _e:
    df_all = pd.DataFrame()
    _load_error = str(_e)

total     = len(df_all)
analyzed  = int(df_all["sentiment"].notna().sum())
df_ana    = df_all[df_all["sentiment"].notna()]
today_str = pd.Timestamp.now().normalize()
today_cnt = int((df_all["published_at"] >= today_str).sum())
ana_pct   = analyzed / total * 100 if total else 0
avg_score = df_ana["impact_score"].mean() if not df_ana.empty else float("nan")
pos_cnt   = int((df_ana["sentiment"] == "正面").sum())
neg_cnt   = int((df_ana["sentiment"] == "負面").sum())
neu_cnt   = int((df_ana["sentiment"] == "中立").sum())
high_rel_cnt = int((df_all["relevance_score"].fillna(-1) >= 70).sum())
pos_pct   = pos_cnt / analyzed * 100 if analyzed else 0
neg_pct   = neg_cnt / analyzed * 100 if analyzed else 0
src_counts = df_all["source"].value_counts()

# Hero：impact 最高的已分析文章
hero_row = (
    df_all[df_all["impact_score"].notna()]
    .sort_values("impact_score", ascending=False)
    .iloc[0] if df_all["impact_score"].notna().any() else None
)

# Top 5：只顯示已分析且 impact_score 不為 NULL 的文章
top5 = (
    df_all[df_all["sentiment"].notna() & df_all["impact_score"].notna()]
    .sort_values("impact_score", ascending=False)
    .head(5)
)

# Keyword stats（已分析文章）
kw_stats = build_keyword_stats(df_ana, top_n=20)
validation_returns = load_validation_returns()

# ─────────────────────────────────────────────────────────────
# 側邊欄
# ─────────────────────────────────────────────────────────────

with st.sidebar:
    # ── 使用者資訊 + 登出 ─────────────────────────────────────
    _uname = st.session_state.get("username", "")
    st.markdown(
        f'<div style="font-size:.82rem;color:#64748b;padding:.4rem 0 .2rem;">'
        f'👤 <b>{_uname}</b></div>',
        unsafe_allow_html=True,
    )
    if st.button("登出", use_container_width=True, type="secondary", key="btn_logout"):
        del st.session_state["username"]
        st.rerun()
    st.divider()

    # ── 頁面入口 ─────────────────────────────────────────────
    st.markdown('<div class="sb-title">頁面</div>', unsafe_allow_html=True)
    page = st.radio(
        "頁面",
        ["Dashboard", "Price Validation"],
        label_visibility="collapsed",
        key="page_nav",
    )
    st.divider()

    # ── 文章統計 + 未分析提醒 ─────────────────────────────────
    unanalyzed = total - analyzed
    st.markdown(
        f'<div style="font-size:.75rem;color:#64748b;line-height:1.7;">'
        f'📋 Total: <b>{total}</b> 篇　'
        f'✅ Analyzed: <b>{analyzed}</b>　'
        f'⏳ Unanalyzed: <b>{unanalyzed}</b>'
        f'</div>',
        unsafe_allow_html=True,
    )
    if unanalyzed > 0:
        st.warning(
            f"⚠️ 有 **{unanalyzed}** 篇新聞尚未分析。\n\n"
            "請執行：\n"
            "`python3 pipeline/update_all.py`\n"
            "或 `python3 pipeline/update_all.py --use-claude`",
            icon=None,
        )
    st.divider()

    st.markdown('<div class="sb-title">篩選條件</div>', unsafe_allow_html=True)

    # ── 重置篩選預設值（透過 session_state）────────────────────
    if st.button("重置篩選", use_container_width=True, key="btn_reset_filters"):
        for _k in ("filter_keyword", "filter_sentiment", "filter_source",
                   "filter_relevance", "filter_sort", "filter_count"):
            if _k in st.session_state:
                del st.session_state[_k]
        st.rerun()

    keyword           = st.text_input("", placeholder="搜尋標題…",
                                      label_visibility="collapsed", key="filter_keyword")
    selected_sentiment = st.selectbox("情緒",
                                      ["全部", "正面", "負面", "中立", "尚未分析"],
                                      key="filter_sentiment")
    source_opts        = ["全部來源"] + sorted(df_all["source"].unique().tolist())
    selected_source    = st.selectbox("來源", source_opts, key="filter_source")
    relevance_filter   = st.selectbox("最低 relevance", ["All", "50+", "70+", "85+"],
                                      index=0, key="filter_relevance")
    sort_by_score      = st.toggle("依影響力排序", value=False, key="filter_sort")
    news_count_option  = st.selectbox("顯示新聞數量", ["10", "20", "50", "All"],
                                      index=1, key="filter_count")
    st.divider()
    if st.button("重新整理", use_container_width=True, key="btn_refresh"):
        st.cache_data.clear()
        st.rerun()

    # ── 資料更新 ──────────────────────────────────────────
    st.divider()
    st.markdown('<div class="sb-title">資料更新</div>', unsafe_allow_html=True)
    st.caption(
        "抓取最新財經新聞，並使用 Rule-Based Analyzer 補分析尚未分析文章。"
        "完成後自動重新整理 Dashboard。"
    )

    # 顯示上一次更新的結果（在 rerun 後呈現）
    _upd_result = st.session_state.pop("_update_result", None)
    if _upd_result == "ok":
        st.success("✅ 更新完成，資料已重新載入。")
    elif _upd_result and _upd_result != "ok":
        st.error(f"⚠️ 更新失敗：{_upd_result}")

    if st.button("🔄 更新新聞", use_container_width=True, key="btn_update_news"):
        _err_msg = None
        with st.spinner("正在更新新聞與分析資料，請稍候…"):
            try:
                # 延遲 import，避免啟動時拖慢頁面載入
                from pipeline.update_all import (          # noqa: PLC0415
                    analyze_pending_articles as _analyze,
                    crawl_all_sources        as _crawl,
                    update_price_validation  as _price,
                )
                from models.db import (                    # noqa: PLC0415
                    create_tables  as _create_tables,
                    get_connection as _get_conn,
                )
                _conn = _get_conn(DB_PATH)
                _create_tables(_conn)
                _crawl(_conn)
                _analyze(_conn, use_claude=False)
                _price(_conn, mock=False, days=30)
                _conn.close()
            except Exception as _e:
                _err_msg = str(_e)

        st.session_state["_update_result"] = "ok" if _err_msg is None else _err_msg
        st.cache_data.clear()
        st.rerun()

    # ── Pipeline 執行狀態 ─────────────────────────────────
    st.markdown("")   # 小間距
    pipe = load_pipeline_status()
    if not pipe:
        dot   = '<span class="pipe-dot-na">●</span>'
        lines = ["尚無執行紀錄", f'資料庫：{pipe.get("db_total", 0)} 篇']
    else:
        has_error = bool(pipe.get("error"))
        dot       = '<span class="pipe-dot-err">●</span>' if has_error \
                    else '<span class="pipe-dot-ok">●</span>'
        ran_at_str = ""
        if pipe.get("ran_at"):
            try:
                ran_dt     = pd.to_datetime(pipe["ran_at"])
                ran_at_str = ran_dt.strftime("%m/%d %H:%M")
            except Exception:
                ran_at_str = str(pipe["ran_at"])[:16]
        raw_mode = str(pipe.get("mode", "—"))
        mode_label = {
            "mock": "rule-based",
            "mock-analysis": "rule-based",
            "mock-prices+rule-based": "rule-based+demo-prices",
            "real": "claude",
        }.get(raw_mode, raw_mode).upper()
        lines = [
            f'最後更新：{ran_at_str}',
            f'模式：{mode_label}',
            f'新增：{pipe.get("inserted", 0)} 篇　分析：{pipe.get("analyzed", 0)} 篇',
            f'資料庫：{pipe.get("db_total", 0)} 篇　耗時 {pipe.get("duration_sec", 0):.0f}s',
        ]
        if has_error:
            lines.append("⚠ 上次執行有錯誤")

    status_body = "<br>".join(lines)
    st.markdown(
        f'<div class="pipe-status">'
        f'<div class="pipe-status-title">{dot} Pipeline 狀態</div>'
        f'{status_body}'
        f'</div>',
        unsafe_allow_html=True,
    )

# ─────────────────────────────────────────────────────────────
# 主頁面結構
# ─────────────────────────────────────────────────────────────
from web.validation_page import render_validation_tab

if page == "Dashboard":

    # ── 頁首 ──────────────────────────────────────────────────
    now_str = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
    st.markdown(f"""
<div class="hdr">
  <div class="hdr-title">台股新聞 AI 分析平台</div>
  <div class="hdr-sub">整合鉅亨網 · Yahoo 股市，以 Rule-Based Financial Analyzer 分析情緒與市場影響力</div>
  <div class="hdr-time">最後更新：{now_str}</div>
</div>""", unsafe_allow_html=True)

    # ── DB 錯誤 / 空狀態（sidebar 已渲染，按鈕可用）─────────────
    if _load_error:
        st.error(f"⚠️ 無法載入資料庫：{_load_error}")
        st.info("若資料庫損毀，可刪除 `data/news.db` 後按「🔄 更新新聞」重建。")
        st.stop()

    if df_all.empty:
        st.info(
            "🗄️ 資料庫尚未建立或目前沒有新聞。\n\n"
            "請按左側 **🔄 更新新聞** 抓取資料，完成後頁面會自動刷新。",
            icon="📭",
        )
        st.stop()

    # ── Hero 卡片 ──────────────────────────────────────────────

    if hero_row is not None:
        reason_text = str(hero_row["reason"] or "")
        reason_short = reason_text[:180] + ("…" if len(reason_text) > 180 else "")
        hero_meta = (
            f'{src_badge(hero_row["source"])}'
            f'&nbsp;{senti_chip(hero_row["sentiment"])}'
            f'&nbsp;{score_pill(hero_row["impact_score"])}'
            f'&nbsp;<span class="ntime">{hero_row["published_at"].strftime("%Y-%m-%d %H:%M") if pd.notna(hero_row["published_at"]) else ""}</span>'
        )
        st.markdown(f"""
<div class="hero-card">
  <div class="hero-eyebrow">今日最重要新聞</div>
  <div class="hero-title"><a href="{hero_row['url']}" target="_blank">{hero_row['title']}</a></div>
  <div class="hero-meta">{hero_meta}</div>
  {f'<div class="hero-reason">{reason_short}</div>' if reason_short else ''}
</div>""", unsafe_allow_html=True)

    # ── 高影響提醒 & 摘要 Insight Bar ─────────────────────────
    high_cnt = int((df_all["impact_score"] >= 8).sum())
    if high_cnt > 3:
        st.markdown(
            f'<div class="alert-high">⚠️ 今日高影響新聞偏多（共 {high_cnt} 篇 impact ≥ 8），建議優先檢視。</div>',
            unsafe_allow_html=True,
        )

    insight_html = _build_insight(today_cnt, avg_score, pos_pct, neg_pct, src_counts, analyzed)
    st.markdown(f'<div class="insight-bar">{insight_html}</div>', unsafe_allow_html=True)

    # ── Metric ────────────────────────────────────────────────
    pos_neg_val = f"{pos_pct:.0f}% / {neg_pct:.0f}%"

    metrics = [
        ("今日新聞",   str(today_cnt),
         f"共 {total} 篇"),
        ("已分析",     f"{ana_pct:.0f}%",
         f"{analyzed} / {total} 篇"),
        ("平均影響力", f"{avg_score:.1f}" if not pd.isna(avg_score) else "—",
         "impact score 均值（1–10）"),
        ("高相關新聞", str(high_rel_cnt),
         "relevance score ≥ 70"),
        ("正面 / 負面", pos_neg_val,
         f"正 {pos_cnt} · 負 {neg_cnt} · 中 {neu_cnt}"),
        ("來源占比",   source_metric_rows(src_counts),
         "各來源文章篇數"),
    ]

    mc_cols = st.columns([1, 1, 1, 1, 1, 1.15], gap="medium")
    for col, (label, value, sub) in zip(mc_cols, metrics):
        value_html = value if label == "來源占比" else f'<div class="mc-value">{value}</div>'
        col.markdown(f"""
<div class="mc">
  <div class="mc-label">{label}</div>
  {value_html}
  <div class="mc-sub">{sub}</div>
</div>""", unsafe_allow_html=True)

    # ── Top Market Drivers ────────────────────────────────────
    st.markdown('<div class="sec-title">🚀 Top Market Drivers</div>', unsafe_allow_html=True)

    if kw_stats.empty:
        st.markdown(
            '<div style="color:#b0b5c3;font-size:.82rem;padding:.4rem 0 .8rem">'
            '尚無 keywords 資料，請執行 <code>python3 pipeline/update_all.py</code>'
            '</div>',
            unsafe_allow_html=True,
        )
    else:
        md_left, md_right = st.columns([1.65, 1], gap="large")

        with md_left:
            # Top 8 Market Driver 卡片
            top_drivers = kw_stats.head(8)
            rank_emojis = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣"]
            for idx, r in enumerate(top_drivers.itertuples(), 0):
                emoji   = rank_emojis[idx] if idx < len(rank_emojis) else f"#{idx+1}"
                related = related_articles_for_driver(df_ana, r.keyword)
                perf = driver_performance(related, validation_returns)
                expander_title = (
                    f"{emoji} {r.keyword} · 出現 {r.count} 次 · "
                    f"avg {r.avg_impact:.1f}/10 · 驅動力 {r.driver_score:.0f}"
                )
                with st.expander(expander_title):
                    st.markdown("**Summary**")
                    sum_cols = st.columns(3)
                    sum_cols[0].metric("相關新聞", f"{len(related)}")
                    sum_cols[1].metric("平均影響力", f"{r.avg_impact:.1f}/10")
                    sum_cols[2].metric("驅動力", f"{r.driver_score:.0f}")

                    render_performance_metrics(perf, "Driver Performance")
                    render_related_news(related, key_prefix=f"driver_{idx}", limit=5)

        with md_right:
            # Keyword Frequency 橫條圖（top 12）
            st.markdown(
                '<div style="font-size:.75rem;color:#8a8f9e;text-transform:uppercase;'
                'letter-spacing:.07em;margin-bottom:.3rem">Keyword Frequency</div>',
                unsafe_allow_html=True,
            )
            freq_df = kw_stats.head(12).copy()
            color_map = {"positive": "#059669", "negative": "#e11d48", "mixed": "#d97706"}
            freq_df["color"] = freq_df["sentiment_mix"].map(color_map)

            bar = (
                alt.Chart(freq_df)
                .mark_bar(cornerRadiusTopRight=3, cornerRadiusBottomRight=3)
                .encode(
                    y=alt.Y("keyword:N", sort="-x",
                            axis=alt.Axis(labelFontSize=10, labelLimit=100)),
                    x=alt.X("count:Q", axis=alt.Axis(tickMinStep=1, labelFontSize=9,
                                                       title="出現次數")),
                    color=alt.Color(
                        "sentiment_mix:N",
                        scale=alt.Scale(
                            domain=["positive", "negative", "mixed"],
                            range=["#059669", "#e11d48", "#d97706"],
                        ),
                        legend=alt.Legend(
                            title="情緒傾向",
                            labelExpr="datum.value === 'positive' ? '正面' : datum.value === 'negative' ? '負面' : '混合'",
                            labelFontSize=10,
                        ),
                    ),
                    tooltip=[
                        alt.Tooltip("keyword:N", title="關鍵字"),
                        alt.Tooltip("count:Q",   title="出現次數"),
                        alt.Tooltip("avg_impact:Q", title="平均影響力", format=".1f"),
                    ],
                )
                .properties(height=340)
                .configure_view(strokeWidth=0)
                .configure_axis(grid=False)
            )
            st.altair_chart(bar, use_container_width=True)

    st.divider()

    # ── High Impact Keywords ──────────────────────────────────
    high_kw_df = df_ana[df_ana["impact_score"] >= 7.0] if not df_ana.empty else pd.DataFrame()
    if not high_kw_df.empty and "keywords_list" in high_kw_df.columns:
        from collections import Counter
        hi_counter: Counter = Counter()
        for kws in high_kw_df["keywords_list"]:
            if isinstance(kws, list):
                hi_counter.update(kws)
        if hi_counter:
            st.markdown(
                '<div class="sec-title">⚡ High Impact Keywords'
                '<span style="font-weight:400;font-size:.72rem;color:#b0b5c3;margin-left:8px">'
                f'impact ≥ 7 的文章共 {len(high_kw_df)} 篇</span></div>',
                unsafe_allow_html=True,
            )
            chips_html = '<div class="hi-kw-grid">'
            for hi_kw, hi_kw_count in hi_counter.most_common(20):
                hi_related = related_articles_for_driver(high_kw_df, hi_kw)
                hi_avg = hi_related["impact_score"].dropna().mean() if not hi_related.empty else float("nan")
                hi_avg_str = f"avg {hi_avg:.1f}/10" if not pd.isna(hi_avg) else "—"
                chips_html += (
                    f'<div class="hi-kw-card">'
                    f'<div class="hi-kw-name">{hi_kw}</div>'
                    f'<div class="hi-kw-meta">出現 {hi_kw_count} 次 · {hi_avg_str}</div>'
                    f'</div>'
                )
            chips_html += '</div>'
            st.markdown(chips_html, unsafe_allow_html=True)
            st.markdown("")

    st.divider()

    # ── Top 5 + Sentiment Pie ─────────────────────────────────
    st.markdown('<div class="sec-title">Top 5 · 最高影響力新聞</div>', unsafe_allow_html=True)

    t5_col, pie_col = st.columns([2.4, 1], gap="large")

    with t5_col:
        if top5.empty:
            st.caption("尚無已分析文章。")
        else:
            for rank, (_, r) in enumerate(top5.iterrows(), 1):
                card_css  = t5_card_css(r["impact_score"])
                title_cut = r["title"][:68] + ("…" if len(r["title"]) > 68 else "")
                st.markdown(f"""
<div class="t5-card {card_css}">
  <div class="t5-rank">#{rank}</div>
  <div class="t5-body">
    <div class="t5-ttl"><a href="{r['url']}" target="_blank">{title_cut}</a></div>
    <div class="t5-chips">
      {src_badge(r['source'])}
      {senti_chip(r['sentiment'])}
    </div>
  </div>
  <div class="t5-right">
    {score_pill(r['impact_score'])}
  </div>
</div>""", unsafe_allow_html=True)

    with pie_col:
        st.markdown('<div class="sec-title">Sentiment Distribution</div>', unsafe_allow_html=True)
        st.caption("已分析新聞的情緒比例")

        if analyzed == 0:
            st.markdown(
                '<div style="color:#b0b5c3;font-size:.78rem;padding:.6rem 0">尚無已分析新聞</div>',
                unsafe_allow_html=True,
            )
        else:
            senti_pie_df = pd.DataFrame({
                "情緒": ["正面", "負面", "中立"],
                "篇數": [pos_cnt, neg_cnt, neu_cnt],
            })
            # 過濾掉 0 篇的類別，避免圓餅圖出現空片
            senti_pie_df = senti_pie_df[senti_pie_df["篇數"] > 0]
            senti_pie = (
                alt.Chart(senti_pie_df)
                .mark_arc(innerRadius=52, outerRadius=92)
                .encode(
                    theta=alt.Theta("篇數:Q"),
                    color=alt.Color(
                        "情緒:N",
                        scale=alt.Scale(
                            domain=["正面", "負面", "中立"],
                            range=["#059669", "#e11d48", "#d97706"],
                        ),
                        legend=alt.Legend(orient="bottom", labelFontSize=11, titleFontSize=0),
                    ),
                    tooltip=["情緒:N", "篇數:Q"],
                )
                .properties(height=240)
                .configure_view(strokeWidth=0)
            )
            st.altair_chart(senti_pie, use_container_width=True)

    # ── 套用篩選 ──────────────────────────────────────────────
    news_df = df_all.copy()

    if keyword:
        news_df = news_df[news_df["title"].str.contains(keyword, case=False, na=False)]
    if selected_sentiment == "尚未分析":
        news_df = news_df[news_df["sentiment"].isna()]
    elif selected_sentiment != "全部":
        news_df = news_df[news_df["sentiment"] == selected_sentiment]
    if selected_source != "全部來源":
        news_df = news_df[news_df["source"] == selected_source]
    if relevance_filter != "All":
        min_relevance = float(relevance_filter.rstrip("+"))
        news_df = news_df[
            news_df["relevance_score"].notna()
            & (news_df["relevance_score"] >= min_relevance)
        ]
    if sort_by_score:
        news_df = news_df.sort_values("impact_score", ascending=False, na_position="last")

    filtered_total = len(news_df)
    if news_count_option == "All":
        display_news_df = news_df
    else:
        display_news_df = news_df.head(int(news_count_option))

    # ── 新聞列表 ──────────────────────────────────────────────
    st.markdown(
        f'<div class="sec-title">新聞列表'
        f'<span style="font-weight:400;text-transform:none;letter-spacing:0;color:#b0b5c3;margin-left:8px">'
        f'顯示 {len(display_news_df)} / {filtered_total} 篇</span></div>',
        unsafe_allow_html=True,
    )

    if display_news_df.empty:
        st.markdown("""
<div class="empty-state">
  <div class="empty-state-icon">🔍</div>
  <div class="empty-state-title">目前篩選條件沒有符合的新聞</div>
  <div class="empty-state-sub">請調整搜尋關鍵字、情緒或來源篩選，或按左側「重置篩選」恢復預設。</div>
</div>""", unsafe_allow_html=True)
    else:
        for idx, row in display_news_df.iterrows():
            is_unanalyzed = pd.isna(row["sentiment"])
            article_id = row["id"] if "id" in row.index and pd.notna(row["id"]) else idx
            article_url = str(row.get("url") or "").strip()
            title_text = str(row.get("title") or "Untitled")
            pub_time = (
                row["published_at"].strftime("%Y-%m-%d %H:%M")
                if pd.notna(row["published_at"]) else "—"
            )
            stock_tag = (
                f'<span class="nstock">{row["stock_codes_str"]}</span>'
                if row["stock_codes_str"] else ""
            )
            kws = row.get("keywords_list", []) if "keywords_list" in row.index else []
            kw_row_html = ""
            if isinstance(kws, list) and kws and not is_unanalyzed:
                kw_row_html = (
                    '<div class="kw-row">'
                    + "".join(f'<span class="kw-chip">{kw}</span>' for kw in kws[:5])
                    + "</div>"
                )
            hi_badge_html = high_impact_badge(row["impact_score"])
            rel_badge_html = relevance_badge(row.get("relevance_score"))
            affected_row_html = affected_stock_chips(
                row.get("affected_stocks_list", [])
                if "affected_stocks_list" in row.index else []
            )
            title_html = (
                f'<a href="{escape(article_url)}" target="_blank">{escape(title_text)}</a>'
                if article_url else escape(title_text)
            )

            with st.container():
                st.markdown(
                    f'<div class="{news_card_class(row)}">'
                    f'<div class="nttl">{title_html}</div>'
                    f'<div class="news-card-badges">'
                    f'{src_badge(row["source"])}'
                    f'<span class="ntime">{pub_time}</span>'
                    f'{senti_chip(row["sentiment"])}'
                    f'{score_pill(row["impact_score"])}'
                    f'{rel_badge_html}'
                    f'{hi_badge_html}'
                    f'{stock_tag}'
                    f'</div>'
                    f'{affected_row_html}'
                    f'{kw_row_html}'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                toggle_label = "AI Analysis · Pending analysis" if is_unanalyzed else "AI Analysis"
                if st.toggle(toggle_label, value=False, key=f"news_analysis_{article_id}"):
                    if is_unanalyzed:
                        st.markdown(format_pending_analysis(), unsafe_allow_html=True)
                    elif pd.notna(row["reason"]) and row["reason"]:
                        st.markdown(format_reason(str(row["reason"])), unsafe_allow_html=True)
                    else:
                        st.markdown(format_reason(""), unsafe_allow_html=True)

        st.caption(f"Showing {len(display_news_df)} of {filtered_total} articles")

else:
    render_validation_tab(DB_PATH)
