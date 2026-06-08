"""
validation_page.py — 股價驗證 Tab

由 web/app.py 的 「📈 Price Validation」 Tab 呼叫：
    from web.validation_page import render_validation_tab
    render_validation_tab(db_path)

功能：
  - 載入真實的 article_returns JOIN articles 資料
  - 若不足 10 筆，自動使用 mock 資料（課堂展示不會空白）
  - 圖表：情緒 vs 報酬率 bar、Impact Score vs |報酬率| scatter、勝率 metrics
  - 底部：原始樣本資料表
"""

import random
import sqlite3
import sys
from pathlib import Path
from typing import Optional

import altair as alt
import pandas as pd
import streamlit as st

# ── 根目錄加入 PYTHONPATH ──────────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from models.db import get_connection
from models.price import get_validation_df

# ─────────────────────────────────────────────────────────────
# Mock 資料產生器（保證課堂展示有內容）
# ─────────────────────────────────────────────────────────────

_SENTIMENTS = ["正面", "負面", "中立"]
_TITLES = [
    "台積電法說會超預期，外資連三買",
    "鴻海 Q3 營收創新高，市場看好",
    "聯發科下調財測，股價跌逾 5%",
    "國泰金爆發利空消息，法人調降評等",
    "台達電取得 AI 伺服器訂單，受惠 NVIDIA 供應鏈",
    "2330 獲利能力持續提升，股息成長可期",
    "半導體業景氣回溫，第四季展望樂觀",
    "科技股修正壓力大，市場避險情緒升溫",
    "台灣 ETF 熱潮持續，台股量能萎縮",
    "外資匯出資金增加，新台幣貶值壓力",
    "IC 設計廠商接單暢旺，Q2 旺季可期",
    "蘋果砍單傳言再起，供應鏈股震盪",
    "Fed 升息預期降溫，風險資產反彈",
    "台股加權指數突破萬八關卡，創歷史新高",
    "鋼鐵族群受惠建設政策，布局中長期",
    "金融股配息優勢凸顯，防禦型買盤進場",
    "AI 概念股回檔整理，技術指標轉弱",
    "南韓三星財報不如預期，台系競爭者受益",
    "電動車電池需求成長，材料股輪漲",
    "台積電 CoWoS 產能擴增，AI 晶片需求強勁",
]
_STOCKS = ["2330", "2317", "2454", "2882", "2308", "2412", "2303", "3008"]


def _gen_mock_df(n: int = 30) -> pd.DataFrame:
    """
    產生模擬驗證資料集。
    設計邏輯：
      - 正面新聞 → return_1d 偏正（+0.5% ~ +3%），但有雜訊
      - 負面新聞 → return_1d 偏負（-3% ~ -0.3%）
      - 高 impact_score → |return| 較大
    """
    random.seed(42)
    rows = []
    for i in range(n):
        sentiment = random.choices(_SENTIMENTS, weights=[0.45, 0.35, 0.2])[0]
        impact    = round(random.uniform(30, 95), 1)
        title     = _TITLES[i % len(_TITLES)]
        stock     = _STOCKS[i % len(_STOCKS)]

        # 報酬率與情緒相關（加入雜訊）
        mag = impact / 100 * 3.5   # 高分 → 大波動
        if sentiment == "正面":
            r1 = round(random.gauss(0.8, mag * 0.6), 2)
        elif sentiment == "負面":
            r1 = round(random.gauss(-0.9, mag * 0.6), 2)
        else:
            r1 = round(random.gauss(0.0, mag * 0.4), 2)

        r3 = round(r1 * random.uniform(0.8, 1.8), 2)
        r5 = round(r1 * random.uniform(0.6, 2.2), 2)

        rows.append({
            "article_id":   i + 1,
            "title":        title,
            "sentiment":    sentiment,
            "impact_score": impact,
            "stock_code":   stock,
            "pub_date":     f"2025-{random.randint(1,12):02d}-{random.randint(1,28):02d}",
            "return_1d":    r1,
            "return_3d":    r3,
            "return_5d":    r5,
        })
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────
# 主渲染函式
# ─────────────────────────────────────────────────────────────

def render_validation_tab(db_path: Path) -> None:
    """
    渲染股價驗證頁面。
    實際資料 < 10 筆時，自動 fallback 到 mock 資料。
    """

    # ── 載入資料 ──────────────────────────────────────────────
    try:
        conn = get_connection(db_path)
        real_df = get_validation_df(conn)
        conn.close()
    except Exception:
        real_df = pd.DataFrame()

    using_mock = False
    if len(real_df) >= 10:
        df = real_df
    else:
        df = _gen_mock_df(30)
        using_mock = True

    # ── 說明 banner ────────────────────────────────────────────
    if using_mock:
        st.info(
            "⚠️  目前真實報酬率資料不足（需先執行 `python3 pipeline/fetch_prices.py --mock`）。"
            "以下使用 **模擬資料** 展示功能。",
            icon="📊",
        )
    else:
        st.success(
            f"✅  已載入 **{len(df)}** 筆真實驗證資料（文章發布後 T+1 日報酬率）",
            icon="📈",
        )

    # ── Section 1: 頂部指標 ────────────────────────────────────
    st.markdown("### 📊 整體驗證指標")

    pos_df  = df[df["sentiment"] == "正面"]
    neg_df  = df[df["sentiment"] == "負面"]
    neu_df  = df[df["sentiment"] == "中立"]

    # 勝率 = 正面新聞後股價上漲的比例
    pos_win = (pos_df["return_1d"] > 0).mean() if len(pos_df) else 0.0
    neg_win = (neg_df["return_1d"] < 0).mean() if len(neg_df) else 0.0
    avg_pos_ret = pos_df["return_1d"].mean() if len(pos_df) else 0.0
    avg_neg_ret = neg_df["return_1d"].mean() if len(neg_df) else 0.0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("正面新聞勝率", f"{pos_win:.1%}", help="正面新聞後 T+1 股價上漲比例")
    col2.metric("負面新聞勝率", f"{neg_win:.1%}", help="負面新聞後 T+1 股價下跌比例")
    col3.metric("正面平均報酬", f"{avg_pos_ret:+.2f}%")
    col4.metric("負面平均報酬", f"{avg_neg_ret:+.2f}%")

    st.divider()

    # ── Section 2: 情緒 vs 報酬率 ─────────────────────────────
    st.markdown("### 🎭 情緒分類 vs T+1 日報酬率")

    col_l, col_r = st.columns([3, 2])

    with col_l:
        # Box plot / bar chart：各情緒的平均 return_1d
        sentiment_summary = (
            df.groupby("sentiment")["return_1d"]
            .agg(["mean", "std", "count"])
            .reset_index()
            .rename(columns={"mean": "平均報酬(%)", "std": "標準差", "count": "篇數"})
        )
        sentiment_summary["情緒"] = sentiment_summary["sentiment"]

        color_map = {
            "正面": "#22c55e",
            "負面": "#ef4444",
            "中立": "#94a3b8",
        }

        bar = (
            alt.Chart(sentiment_summary)
            .mark_bar(cornerRadiusTopLeft=5, cornerRadiusTopRight=5)
            .encode(
                x=alt.X("情緒:N", axis=alt.Axis(labelFontSize=13)),
                y=alt.Y("平均報酬(%):Q",
                        axis=alt.Axis(title="T+1 日平均報酬率 (%)")),
                color=alt.Color(
                    "情緒:N",
                    scale=alt.Scale(
                        domain=list(color_map.keys()),
                        range=list(color_map.values()),
                    ),
                    legend=None,
                ),
                tooltip=["情緒", "平均報酬(%)", "標準差", "篇數"],
            )
            .properties(height=300, title="各情緒類別平均 T+1 報酬率")
        )
        # 加一條零軸
        rule = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(
            color="#64748b", strokeDash=[4, 4]
        ).encode(y="y:Q")
        st.altair_chart(bar + rule, use_container_width=True)

    with col_r:
        # 散點：每篇文章 sentiment vs return_1d（jitter）
        scatter_df = df.copy()
        # 加入小 jitter 避免重疊
        scatter_df["jitter"] = [random.uniform(-0.3, 0.3) for _ in range(len(df))]
        scatter_df["sentiment_n"] = scatter_df["sentiment"].map(
            {"正面": 2, "中立": 1, "負面": 0}
        )

        scatter = (
            alt.Chart(scatter_df)
            .mark_circle(opacity=0.55, size=50)
            .encode(
                x=alt.X("return_1d:Q", axis=alt.Axis(title="T+1 日報酬率 (%)")),
                y=alt.Y("sentiment:N", axis=alt.Axis(title="")),
                color=alt.Color(
                    "sentiment:N",
                    scale=alt.Scale(
                        domain=list(color_map.keys()),
                        range=list(color_map.values()),
                    ),
                    legend=None,
                ),
                tooltip=["title", "sentiment", "impact_score", "return_1d"],
            )
            .properties(height=300, title="每篇文章報酬率分佈")
        )
        st.altair_chart(scatter, use_container_width=True)

    st.divider()

    # ── Section 3: Impact Score vs 波動度 ─────────────────────
    st.markdown("### 🎯 Impact Score vs 絕對報酬率（波動度）")

    impact_df = df.copy()
    impact_df["|return_1d|"] = impact_df["return_1d"].abs()
    impact_df["impact_bucket"] = pd.cut(
        impact_df["impact_score"],
        bins=[0, 30, 50, 70, 85, 100],
        labels=["0–30", "31–50", "51–70", "71–85", "86–100"],
    )

    col_a, col_b = st.columns([3, 2])
    with col_a:
        # Scatter: impact_score vs |return_1d|
        s2 = (
            alt.Chart(impact_df)
            .mark_circle(opacity=0.6, size=60)
            .encode(
                x=alt.X("impact_score:Q", axis=alt.Axis(title="Impact Score")),
                y=alt.Y("|return_1d|:Q", axis=alt.Axis(title="|T+1 報酬率| (%)")),
                color=alt.Color(
                    "sentiment:N",
                    scale=alt.Scale(
                        domain=list(color_map.keys()),
                        range=list(color_map.values()),
                    ),
                ),
                tooltip=["title", "impact_score", "return_1d", "sentiment", "stock_code"],
            )
            .properties(height=300, title="Impact Score vs 絕對報酬率")
        )
        # 趨勢線
        trend = s2.transform_regression(
            "impact_score", "|return_1d|", method="linear"
        ).mark_line(color="#6366f1", strokeDash=[5, 3], strokeWidth=2)
        st.altair_chart(s2 + trend, use_container_width=True)

    with col_b:
        # Bar: impact bucket 平均 |return|
        bucket_summary = (
            impact_df.groupby("impact_bucket", observed=True)["|return_1d|"]
            .mean()
            .reset_index()
            .rename(columns={"|return_1d|": "平均|報酬|(%)", "impact_bucket": "Impact 區間"})
        )
        b2 = (
            alt.Chart(bucket_summary)
            .mark_bar(color="#6366f1", cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
            .encode(
                x=alt.X("Impact 區間:N"),
                y=alt.Y("平均|報酬|(%):Q"),
                tooltip=["Impact 區間", "平均|報酬|(%)"],
            )
            .properties(height=300, title="Impact 等級 vs 平均波動")
        )
        st.altair_chart(b2, use_container_width=True)

    st.divider()

    # ── Section 4: 樣本資料表 ─────────────────────────────────
    st.markdown("### 📋 驗證樣本資料")

    show_df = (
        df[["title", "sentiment", "impact_score", "stock_code", "pub_date",
            "return_1d", "return_3d", "return_5d"]]
        .rename(columns={
            "title":        "標題",
            "sentiment":    "情緒",
            "impact_score": "Impact",
            "stock_code":   "股票",
            "pub_date":     "發布日",
            "return_1d":    "T+1(%)",
            "return_3d":    "T+3(%)",
            "return_5d":    "T+5(%)",
        })
        .sort_values("發布日", ascending=False)
        .head(50)
    )

    # 情緒欄位顏色函式
    def _color_sentiment(val: str) -> str:
        if val == "正面":
            return "color: #16a34a; font-weight:600"
        if val == "負面":
            return "color: #dc2626; font-weight:600"
        return "color: #64748b"

    def _color_return(val: float) -> str:
        try:
            v = float(val)
            if v > 0:
                return "color: #16a34a"
            if v < 0:
                return "color: #dc2626"
        except Exception:
            pass
        return ""

    styled = (
        show_df.style
        .map(_color_sentiment, subset=["情緒"])
        .map(_color_return, subset=["T+1(%)", "T+3(%)", "T+5(%)"])
        .format({"Impact": "{:.1f}", "T+1(%)": "{:+.2f}", "T+3(%)": "{:+.2f}", "T+5(%)": "{:+.2f}"})
    )
    st.dataframe(styled, use_container_width=True, height=380)

    # ── 資料來源說明 ───────────────────────────────────────────
    data_tag = "🎭 模擬資料（Mock）" if using_mock else f"✅ 真實資料（{len(df)} 筆）"
    st.caption(
        f"資料來源：{data_tag}　｜　"
        "T+1/T+3/T+5 = 新聞發布後第 1/3/5 個交易日的收盤報酬率　｜　"
        "股價資料來源：yfinance"
    )
