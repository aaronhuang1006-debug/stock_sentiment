"""
mock_sentiment.py — Rule-Based Analyzer（不呼叫 Claude API）

依照標題與內容做財經關鍵字比對，產生 sentiment / impact_score /
reason / keywords。適用於 ANTHROPIC_API_KEY 沒額度、Demo，或離線測試。
結果是規則式近似判斷，不代表真實市場建議。
"""

import re
from typing import Optional

from analysis.sentiment import SentimentResult

# ── 市場關鍵字抽取詞典 ────────────────────────────────────────
# 格式：(正規表示式或字串, 標準化顯示名稱)
# 先比對 title + content，命中的取前 5 個；不足時用情緒 fallback 補齊
_KW_PATTERNS: list[tuple[str, str]] = [
    # 技術 / 產品
    (r"CoWoS",        "CoWoS封裝"),
    (r"HBM",          "HBM記憶體"),
    (r"ASIC",         "ASIC晶片"),
    (r"GB200|GH200|H100|H200|B200", "輝達AI晶片"),
    (r"液冷|水冷散熱",  "液冷散熱"),
    (r"AI伺服器|AI server", "AI伺服器"),
    (r"邊緣運算|Edge AI",   "邊緣運算"),
    (r"電動車|EV\b",   "電動車"),
    (r"儲能|電池",     "儲能電池"),
    (r"晶圓代工|foundry", "晶圓代工"),
    (r"先進封裝|advanced packaging", "先進封裝"),
    (r"3nm|2nm|5nm",  "先進製程"),
    (r"DRAM|HBM|DDR", "記憶體"),
    (r"NAND|Flash",   "Flash儲存"),
    (r"PCB|電路板",    "PCB電路板"),
    (r"散熱|熱管",     "散熱模組"),
    (r"伺服器|server", "伺服器"),
    (r"AI.*伺服器|伺服器.*AI", "AI伺服器"),
    (r"資料中心|data center", "資料中心"),
    (r"網通|交換器",   "網通設備"),
    (r"光模組|光纖",   "光模組"),
    # 事件 / 財務
    (r"法說會",        "法說會"),
    (r"營收",          "營收表現"),
    (r"營收年減",      "營收年減"),
    (r"獲利|EPS|每股盈餘", "獲利展望"),
    (r"下修|下調",     "獲利下修"),
    (r"上修|上調|調升", "評等調升"),
    (r"庫存",          "庫存調整"),
    (r"漲價|提價",     "漲價題材"),
    (r"降價|砍價",     "價格壓力"),
    (r"訂單",          "訂單能見度"),
    (r"接單",          "接單動能"),
    (r"擴產|增產",     "產能擴充"),
    (r"裁員|減班",     "人力縮編"),
    (r"併購|收購",     "併購題材"),
    (r"分拆|spin.?off", "業務分拆"),
    (r"配息|股息|殖利率", "股息配發"),
    (r"回購|買回",     "庫藏股"),
    # 大廠名稱
    (r"台積電|TSMC",   "台積電"),
    (r"輝達|NVIDIA|nVidia", "輝達"),
    (r"蘋果|Apple",    "蘋果供應鏈"),
    (r"AMD",           "AMD"),
    (r"英特爾|Intel",  "英特爾"),
    (r"三星|Samsung",  "三星"),
    (r"聯發科|MediaTek", "聯發科"),
    (r"鴻海|富士康",   "鴻海"),
    # 總經 / 指數
    (r"Fed|聯準會|升息|降息", "Fed政策"),
    (r"美中貿易|關稅",  "貿易關稅"),
    (r"外資|QFII",     "外資動向"),
    (r"外資.*買超|買超", "外資買超"),
    (r"外資.*賣超|賣超", "外資賣超"),
]

# Fallback 詞庫（依情緒）
_KW_FALLBACK = {
    "正面": ["業績優於預期", "外資買超", "法說會樂觀", "訂單能見度佳"],
    "負面": ["獲利下修", "庫存調整", "訂單減少", "評等調降"],
    "中立": ["財報公布", "產能利用率", "匯率影響", "產業觀察"],
}


def _extract_keywords(text: str, sentiment: str) -> list[str]:
    """
    從 title + content 依詞典抽取關鍵字，不足 3 個時用 fallback 補齊。
    最多回傳 5 個，去重。
    """
    found: list[str] = []
    seen: set[str] = set()
    for pattern, label in _KW_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE) and label not in seen:
            found.append(label)
            seen.add(label)
        if len(found) >= 5:
            break

    # 不足 3 個時從 fallback 補（不重複）
    if len(found) < 3:
        for fb in _KW_FALLBACK.get(sentiment, _KW_FALLBACK["中立"]):
            if fb not in seen:
                found.append(fb)
                seen.add(fb)
            if len(found) >= 3:
                break

    return found[:5]

# ── 情緒關鍵字 ────────────────────────────────────────────────
_POSITIVE_WORDS = [
    "獲利", "成長", "突破", "得標", "合約", "上調", "買進", "超越", "創高",
    "利多", "受惠", "訂單", "擴產", "轉盈", "調升", "大增", "新高", "強勁",
    "創紀錄", "優於預期", "大幅成長", "大客戶", "量產", "重大合作",
    "買超", "接單", "上修", "法說樂觀", "需求強勁",
]
_NEGATIVE_WORDS = [
    "虧損", "衰退", "下調", "賣出", "裁員", "訴訟", "中斷", "召回", "警示",
    "利空", "下修", "虧", "跌", "減少", "停產", "停工", "違約", "罰款",
    "低於預期", "大幅衰退", "重大損失", "轉虧",
    "砍單", "賣超", "庫存過高", "毛利下滑", "營收年減",
]
_NEUTRAL_WORDS = [
    "公告", "法說會", "股東會", "除權息", "營收公布", "董事會", "例行訊息",
]

# ── 規模關鍵字 ────────────────────────────────────────────────
# 大型權值股代號 or 公司名稱
_LARGE_CAP = [
    "台積電", "2330", "聯發科", "2454", "鴻海", "2317", "台達電", "2308",
    "聯電", "2303", "日月光", "3711", "廣達", "2382", "緯創", "3231",
    "華碩", "2357", "技嘉", "2376", "富士康", "中華電", "2412",
]
_MID_CAP_SIGNALS = ["億元", "百億", "十億"]

# ── 確定性關鍵字 ──────────────────────────────────────────────
_HIGH_CERTAINTY = ["已簽約", "正式合約", "量產", "實際出貨", "宣布", "公告"]
_LOW_CERTAINTY  = ["傳出", "據悉", "消息指出", "備忘錄", "MOU", "規劃", "洽談中"]
_HIGH_IMPACT_WORDS = [
    "財報", "營收", "獲利", "法說會", "外資", "AI", "半導體", "台積電",
    "輝達", "記憶體", "伺服器",
]
_LOW_IMPACT_WORDS = [
    "例行公告", "日期", "股東會", "除息", "除權息", "董事會", "一般行政資訊",
]


def _count_matches(text: str, keywords: list[str]) -> int:
    return sum(1 for kw in keywords if kw in text)


def mock_analyze(
    title: str,
    content: Optional[str],
    stock_codes: list,
    keywords_only: bool = False,
) -> SentimentResult:
    """
    以關鍵字規則產生 rule-based 分析結果。
    """
    full_text = title + " " + (content or "")[:800]

    # ── 1. 情緒判斷 ────────────────────────────────────────────
    pos = _count_matches(full_text, _POSITIVE_WORDS)
    neg = _count_matches(full_text, _NEGATIVE_WORDS)
    neu = _count_matches(full_text, _NEUTRAL_WORDS)

    if pos > neg and pos > 0:
        sentiment = "正面"
    elif neg > pos and neg > 0:
        sentiment = "負面"
    elif neu > 0:
        sentiment = "中立"
    else:
        sentiment = "中立"

    # ── 2. 四維度評估 ──────────────────────────────────────────
    # A. 公司規模
    is_large_cap = any(kw in full_text for kw in _LARGE_CAP) or bool(stock_codes)
    has_mid_cap  = any(kw in full_text for kw in _MID_CAP_SIGNALS)
    if is_large_cap:
        scale_score = 3   # 大型權值股
        scale_note  = f"涉及{'、'.join(stock_codes) if stock_codes else '大型'}權值股"
    elif has_mid_cap:
        scale_score = 2   # 中型
        scale_note  = "涉及中型公司，具一定市場規模"
    else:
        scale_score = 1   # 小型或不明
        scale_note  = "公司規模較小或未明確揭示"

    # B. 獲利影響
    has_number   = bool(re.search(r"\d+\.?\d*\s*[億萬%％]", full_text))
    high_certain = any(kw in full_text for kw in _HIGH_CERTAINTY)
    low_certain  = any(kw in full_text for kw in _LOW_CERTAINTY)

    if has_number and high_certain:
        profit_score = 3
        profit_note  = "有具體財務數字且確定性高"
    elif has_number or high_certain:
        profit_score = 2
        profit_note  = "有部分財務數字或確認訊號，但完整性不足"
    elif low_certain:
        profit_score = 1
        profit_note  = "消息仍屬傳聞或計畫階段，確定性低"
    else:
        profit_score = 1
        profit_note  = "無具體財務數字，獲利影響不明"

    # C. 市場影響
    is_rare_event = pos >= 3 or neg >= 3
    if is_rare_event:
        market_score = 2
        market_note  = "具多項正/負面訊號，屬非例行性市場事件"
    else:
        market_score = 1
        market_note  = "屬例行性公告或一般市場資訊"

    # D. 指數影響
    # 大型權值股且有實質財務影響才可能連動指數
    if is_large_cap and profit_score >= 2:
        index_score = 2
        index_note  = "大型權值股有財務影響，具一定指數連動可能"
    else:
        index_score = 1
        index_note  = "影響侷限於個股，指數連動性低"

    # ── 3. 加總計算 impact_score（1–10）─────────────────────────
    high_impact_hits = _count_matches(full_text, _HIGH_IMPACT_WORDS)
    low_impact_hits = _count_matches(full_text, _LOW_IMPACT_WORDS)
    raw = scale_score + profit_score + market_score + index_score  # 4–10
    raw += min(high_impact_hits, 3) * 0.4
    raw -= min(low_impact_hits, 3) * 0.5
    if sentiment in {"正面", "負面"}:
        raw += min(max(pos, neg), 3) * 0.2
    impact_score = round(float(max(1, min(10, raw))), 1)

    # ── 4. 找出主要加分原因 ────────────────────────────────────
    dim_scores = {
        "公司規模": scale_score,
        "獲利影響": profit_score,
        "市場影響": market_score,
        "指數影響": index_score,
    }
    top_dims = [k for k, v in dim_scores.items() if v == max(dim_scores.values())]
    top_label = "、".join(top_dims)

    # ── 5. 抽取市場關鍵字 ──────────────────────────────────────
    keywords = _extract_keywords(full_text, sentiment)

    sentiment_label = {"正面": "Positive", "負面": "Negative", "中立": "Neutral"}[sentiment]
    signal_note = {
        "正面": "文章包含正面財務或需求訊號",
        "負面": "文章包含負面營運或市場壓力訊號",
        "中立": "文章偏例行公告或資訊揭露，缺乏明確多空方向",
    }[sentiment]
    impact_note = (
        "關鍵字包含高影響族群或事件，可能影響市場預期"
        if high_impact_hits
        else "未出現明顯高影響族群或重大事件關鍵字"
    )
    keyword_note = "、".join(keywords[:3]) if keywords else "無明確關鍵字"
    reason = (
        "AI Analysis:\n"
        f"- {signal_note}\n"
        f"- 關鍵字包含 {keyword_note}\n"
        f"- {impact_note}\n"
        f"- 四維度主要加分原因：{top_label}；{scale_note}；{profit_note}\n"
        f"- 因此判定為 {sentiment_label}，impact score 為 {impact_score:.1f}"
    )

    return SentimentResult(
        sentiment=sentiment,
        impact_score=impact_score,
        reason=reason,
        keywords=keywords,
        raw_response="[MOCK]",
    )
