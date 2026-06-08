"""
Rule-Based Financial Analyzer

這是 Claude API 不可用時的 fallback engine。它不假裝是 LLM，而是用可解釋的
事件分類、產業分類、風險判讀、否定語境與信心分數，產生 sentiment /
impact_score / reason / keywords。保留 mock_analyze 函式名稱，讓既有 pipeline
可以無痛改用 rule-based 分析結果。
"""

import re
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.sentiment import SentimentResult


POSITIVE_SIGNALS: list[tuple[str, float, str, str]] = [
    (r"營收創高|營收.*創.*高|創同期新高|改寫新高", 4.0, "營收創高", "營收表現"),
    (r"獲利成長|獲利.*成長|EPS.*成長", 4.0, "獲利成長", "獲利成長"),
    (r"優於預期|超乎預期|高於預期", 4.0, "優於預期", "獲利成長"),
    (r"外資買超", 3.0, "外資買超", "外資買超"),
    (r"重大訂單|訂單增加|訂單滿載|接單增加|接單暢旺", 3.0, "訂單增加", "供應鏈"),
    (r"AI需求爆發|AI需求|AI.*需求|供不應求", 3.0, "AI需求", "AI伺服器"),
    (r"伺服器需求|伺服器.*需求", 3.0, "伺服器需求", "AI伺服器"),
    (r"價格上漲|報價上揚|漲價", 3.0, "報價上揚", "營收表現"),
    (r"擴產|增產", 2.0, "擴產", "供應鏈"),
    (r"法說樂觀|法說.*樂觀|展望樂觀", 2.0, "法說樂觀", "法說會"),
    (r"股利增加|配息增加|提高股利", 2.0, "股利增加", "股利政策"),
    (r"上修展望|上修.*展望|調升展望", 4.0, "上修展望", "獲利成長"),
    (r"毛利率改善|毛利率回升|毛利.*改善|毛利.*回升", 3.0, "毛利率改善", "獲利成長"),
    (r"虧損收斂|虧損.*收斂", 1.5, "虧損收斂", "財務風險"),
    (r"轉虧為盈", 4.0, "轉虧為盈", "獲利成長"),
]

NEGATIVE_SIGNALS: list[tuple[str, float, str, str]] = [
    (r"不如預期|低於預期", -4.0, "不如預期", "獲利下修"),
    (r"獲利下修|下修.*獲利", -4.0, "獲利下修", "獲利下修"),
    (r"營收年減|營收.*年減", -3.0, "營收年減", "營收表現"),
    (r"營收年增", 2.0, "營收年增", "營收表現"),
    (r"虧損|轉盈為虧|連續虧損", -4.0, "虧損", "財務風險"),
    (r"外資賣超", -3.0, "外資賣超", "外資賣超"),
    (r"砍單|訂單.*減少", -4.0, "砍單", "供應鏈"),
    (r"庫存過高|庫存.*過高|庫存去化", -3.0, "庫存調整", "庫存調整"),
    (r"毛利率下滑|毛利.*下滑|毛利承壓", -3.0, "毛利率下滑", "獲利下修"),
    (r"裁員|減班休息", -3.0, "裁員", "財務風險"),
    (r"法說保守|法說.*保守|展望保守", -2.0, "法說保守", "法說會"),
    (r"需求疲弱|需求放緩|需求.*疲弱|需求.*放緩", -3.0, "需求疲弱", "供應鏈"),
    (r"報價下跌|價格下滑|跌價", -3.0, "報價下跌", "營收表現"),
    (r"降評|調降評等|評等調降", -3.0, "降評", "獲利下修"),
    (r"退票", -4.0, "退票", "財務風險"),
    (r"財務危機|債務危機|違約|下市風險", -5.0, "財務危機", "財務風險"),
    (r"重大訴訟|訴訟|被告|求償|裁罰", -3.0, "訴訟", "訴訟風險"),
]

NEGATED_POSITIVE_PATTERNS = [
    r"未見明顯成長",
    r"未見.*成長",
    r"沒有.*成長",
    r"成長.*不明顯",
    r"不如預期",
]

NEGATED_NEGATIVE_PATTERNS = [
    r"沒有砍單",
    r"未砍單",
    r"並未砍單",
    r"無砍單",
    r"未下修",
    r"沒有下修",
    r"並未下修",
    r"沒有虧損",
    r"未見虧損",
    r"虧損收斂",
    r"虧損.*收斂",
]

NEGATED_CONTEXT_PATTERNS = NEGATED_POSITIVE_PATTERNS + NEGATED_NEGATIVE_PATTERNS

NEUTRAL_SIGNALS = [
    "公告",
    "董事會",
    "股東會",
    "除權息",
    "法說會",
    "營收公布",
    "例行資訊",
    "代子公司公告",
]

EVENT_PATTERNS: list[tuple[str, str]] = [
    ("financial_distress", r"退票|財務危機|債務危機|違約|資金缺口|下市風險"),
    ("legal_risk", r"重大訴訟|訴訟|被告|求償|裁罰|罰款"),
    ("foreign_investor", r"外資|買超|賣超"),
    ("ai_semiconductor", r"台積電|輝達|NVIDIA|AI|半導體|記憶體|HBM|伺服器"),
    ("guidance", r"上修|下修|展望|法說樂觀|法說保守|需求疲弱|需求放緩|降評"),
    ("earnings", r"財報|獲利|EPS|毛利率|盈餘|轉虧為盈|轉盈為虧|虧損"),
    ("revenue", r"營收|營收創高|營收年減|營收年增|營收公布"),
    ("dividend", r"股利|配息|除權息"),
    ("macro_fx", r"匯率|台幣|新台幣|美元|Fed|聯準會|升息|降息"),
    ("supply_chain", r"供應鏈|砍單|接單|訂單|庫存|擴產|報價|價格"),
    ("routine_announcement", r"例行公告|公告|董事會|股東會|代子公司公告|例行資訊"),
]

SECTOR_PATTERNS: list[tuple[str, str]] = [
    ("ai_server", r"AI伺服器|AI.*伺服器|伺服器.*AI|輝達|NVIDIA|GB200|GB300"),
    ("memory", r"記憶體|HBM|DRAM|NAND|DDR|Flash"),
    ("semiconductor", r"半導體|台積電|晶圓|IC設計|先進製程|封裝|CoWoS|聯發科"),
    ("financial", r"金融|銀行|金控|保險|券商|外資|利差"),
    ("shipping", r"航運|貨櫃|海運|運價|散裝|長榮|陽明|萬海"),
    ("biotech", r"生技|新藥|臨床|醫材|疫苗|藥證"),
    ("construction", r"營建|建設|房市|推案|都更|建案"),
    ("retail", r"零售|百貨|通路|電商|超商|消費"),
    ("energy", r"能源|太陽能|風電|電力|儲能|油價"),
    ("macro", r"匯率|台幣|美元|Fed|聯準會|升息|降息|CPI|通膨|景氣"),
]

HIGH_SEVERITY_RE = re.compile(
    r"財務危機|退票|重大訴訟|獲利下修|營收創高|優於預期|重大訂單|AI需求爆發|"
    r"轉虧為盈|轉盈為虧|下市風險"
)
MEDIUM_SEVERITY_RE = re.compile(
    r"營收年增|外資買超|外資賣超|法說會|擴產|庫存調整|庫存去化|股利|配息|"
    r"報價上揚|報價下跌|價格上漲|價格下滑"
)
LOW_SEVERITY_RE = re.compile(r"董事會|股東會|除權息|代子公司公告|一般公告|例行公告")
LOSS_NARROWING_RE = re.compile(r"虧損收斂|虧損.*收斂")

MARKET_SENSITIVE_RE = re.compile(
    r"台積電|輝達|NVIDIA|AI|半導體|記憶體|HBM|DRAM|NAND|伺服器",
    re.IGNORECASE,
)
FINANCIAL_EVENT_RE = re.compile(r"財報|營收|獲利|法說會|EPS|毛利率")
FOREIGN_INVESTOR_RE = re.compile(r"外資買超|外資賣超")
SEVERE_NEGATIVE_RE = re.compile(r"下修|虧損|退票|財務危機|違約|下市風險")
ROUTINE_RE = re.compile(r"例行公告|董事會|股東會|除權息|一般公告")
SUBSIDIARY_RE = re.compile(r"代子公司公告")
COMPANY_INDUSTRY_RE = re.compile(
    r"\b\d{4}\b|台積電|聯發科|鴻海|台達電|廣達|緯創|華碩|技嘉|"
    r"AI|半導體|記憶體|伺服器|電子|金融|航運|鋼鐵|生技|電動車|供應鏈|能源|營建",
    re.IGNORECASE,
)
AI_CLUSTER_RE = re.compile(r"(?=.*(?:AI|輝達|NVIDIA))(?=.*(?:台積電|伺服器))", re.IGNORECASE)

STANDARD_KEYWORDS: list[tuple[str, str, str]] = [
    ("event", r"AI需求爆發|AI需求|AI伺服器|AI.*伺服器|伺服器.*AI|伺服器需求", "AI伺服器"),
    ("sector", r"半導體|台積電|晶圓|先進製程|封裝", "半導體"),
    ("sector", r"記憶體|HBM|DRAM|NAND", "記憶體"),
    ("event", r"營收創高|營收年減|營收年增|營收公布|營收", "營收表現"),
    ("event", r"獲利成長|優於預期|毛利率改善|轉虧為盈|EPS", "獲利成長"),
    ("event", r"獲利下修|下修|降評|毛利率下滑|轉盈為虧", "獲利下修"),
    ("market", r"外資買超", "外資買超"),
    ("market", r"外資賣超", "外資賣超"),
    ("event", r"法說會|法說", "法說會"),
    ("event", r"財報", "財報公布"),
    ("event", r"股利|配息|除權息", "股利政策"),
    ("market", r"匯率|台幣|新台幣|美元", "匯率影響"),
    ("risk", r"庫存|庫存過高|庫存去化", "庫存調整"),
    ("event", r"供應鏈|訂單|接單|砍單|擴產|報價|價格", "供應鏈"),
    ("risk", r"財務危機|退票|違約|虧損|債務|下市風險", "財務風險"),
    ("risk", r"重大訴訟|訴訟|被告|求償|裁罰", "訴訟風險"),
    ("event", r"例行公告|公告|董事會|股東會|代子公司公告|例行資訊", "例行公告"),
]

KEYWORD_PRIORITY = {"event": 0, "sector": 1, "risk": 2, "market": 3}


def _is_negated(text: str, pattern: str, negative_signal: bool) -> bool:
    context_patterns = NEGATED_NEGATIVE_PATTERNS if negative_signal else NEGATED_POSITIVE_PATTERNS
    for match in re.finditer(pattern, text, re.IGNORECASE):
        start = max(0, match.start() - 8)
        end = min(len(text), match.end() + 8)
        window = text[start:end]
        if any(re.search(context_pattern, window, re.IGNORECASE) for context_pattern in context_patterns):
            return True
    return False


def _strip_negated_context(text: str) -> str:
    cleaned = text
    for pattern in NEGATED_CONTEXT_PATTERNS:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    return cleaned


def _weighted_hits(
    title: str,
    content: Optional[str],
    signals: list[tuple[str, float, str, str]],
) -> tuple[float, list[dict]]:
    score = 0.0
    hits: list[dict] = []
    body = content or ""

    for pattern, weight, label, keyword in signals:
        contribution = 0.0
        title_hit = bool(re.search(pattern, title, re.IGNORECASE))
        content_hit = bool(body and re.search(pattern, body, re.IGNORECASE))
        negative_signal = weight < 0

        if title_hit and not _is_negated(title, pattern, negative_signal):
            contribution += weight * 1.5
        if content_hit and not _is_negated(body, pattern, negative_signal):
            contribution += weight

        if contribution:
            score += contribution
            hits.append(
                {
                    "label": label,
                    "keyword": keyword,
                    "base_weight": weight,
                    "contribution": contribution,
                }
            )

    return score, hits


def _classify_event_type(text: str) -> str:
    for event_type, pattern in EVENT_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return event_type
    return "unknown"


def _classify_sector(text: str) -> str:
    for sector, pattern in SECTOR_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return sector
    return "unknown"


def _event_severity(text: str, event_type: str, signal_hits: list[dict]) -> str:
    if LOSS_NARROWING_RE.search(text) and event_type not in {"financial_distress", "legal_risk"}:
        return "medium"
    if HIGH_SEVERITY_RE.search(text) or event_type in {"financial_distress", "legal_risk"}:
        return "high"
    if any(abs(float(hit["base_weight"])) >= 4 for hit in signal_hits):
        return "high"
    if MEDIUM_SEVERITY_RE.search(text) or any(abs(float(hit["base_weight"])) >= 2 for hit in signal_hits):
        return "medium"
    if LOW_SEVERITY_RE.search(text) or event_type == "routine_announcement":
        return "low"
    return "low"


def _confidence(signal_hits: list[dict], event_severity: str, event_type: str) -> str:
    strong_hit_count = sum(1 for hit in signal_hits if abs(float(hit["base_weight"])) >= 3)
    if strong_hit_count >= 3:
        return "High"
    if strong_hit_count >= 1:
        return "Medium"
    if event_type == "routine_announcement" or event_severity == "low":
        return "Low"
    return "Low"


def _has_strong_directional_signal(hits: list[dict]) -> bool:
    return any(abs(float(hit["base_weight"])) >= 3 for hit in hits)


def _impact_score(
    text: str,
    signal_hits: list[dict],
    event_type: str,
    sector: str,
    event_severity: str,
    confidence: str,
) -> float:
    score = 3.0

    clean_text = _strip_negated_context(text)
    severe_text = clean_text
    if LOSS_NARROWING_RE.search(text):
        severe_text = re.sub(r"虧損", " ", severe_text)

    if MARKET_SENSITIVE_RE.search(clean_text):
        score += 2.0
    if FINANCIAL_EVENT_RE.search(clean_text):
        score += 1.5
    if FOREIGN_INVESTOR_RE.search(clean_text):
        score += 1.0
    if SEVERE_NEGATIVE_RE.search(severe_text):
        score += 2.0

    strong_hit_count = sum(1 for hit in signal_hits if abs(float(hit["base_weight"])) >= 3)
    if strong_hit_count >= 2:
        score += 1.0

    if sector in {"semiconductor", "ai_server", "memory"}:
        score += 1.0
    if event_severity == "high":
        score += 2.0
    elif event_severity == "medium":
        score += 1.0
    else:
        score -= 1.0
    if confidence == "High":
        score += 0.5

    if ROUTINE_RE.search(clean_text):
        score -= 1.5
    if SUBSIDIARY_RE.search(clean_text):
        score -= 1.0
    if not COMPANY_INDUSTRY_RE.search(clean_text):
        score -= 1.0

    if event_type == "routine_announcement" and event_severity != "high":
        score = min(score, 4.0)
    if event_type == "financial_distress":
        score = max(score, 7.0)
    if AI_CLUSTER_RE.search(clean_text):
        score = max(score, 7.5)

    return round(max(1.0, min(10.0, score)), 1)


def _standardize_keywords(text: str, signal_hits: list[dict]) -> list[str]:
    candidates: list[tuple[int, str]] = []
    seen: set[str] = set()
    clean_text = _strip_negated_context(text)

    for hit in signal_hits:
        keyword = str(hit["keyword"])
        if keyword not in seen:
            category = "risk" if "風險" in keyword or "下修" in keyword else "event"
            candidates.append((KEYWORD_PRIORITY[category], keyword))
            seen.add(keyword)

    for category, pattern, keyword in STANDARD_KEYWORDS:
        if re.search(pattern, clean_text, re.IGNORECASE) and keyword not in seen:
            candidates.append((KEYWORD_PRIORITY[category], keyword))
            seen.add(keyword)

    if not candidates:
        fallback = "例行公告" if re.search(r"公告|董事會|股東會", text) else "營收表現"
        candidates.append((KEYWORD_PRIORITY["event"], fallback))

    candidates.sort(key=lambda item: item[0])
    return [keyword for _, keyword in candidates[:5]]


def _labels_for_reason(hits: list[dict]) -> str:
    sorted_hits = sorted(hits, key=lambda item: abs(float(item["contribution"])), reverse=True)
    labels = []
    seen = set()
    for hit in sorted_hits:
        label = str(hit["label"])
        if label not in seen:
            labels.append(f"「{label}」")
            seen.add(label)
        if len(labels) >= 3:
            break
    return "、".join(labels) if labels else "無明確方向性強訊號"


def _build_reason(
    sentiment: str,
    impact_score: float,
    event_type: str,
    sector: str,
    event_severity: str,
    confidence: str,
    signal_hits: list[dict],
) -> str:
    sentiment_label = {"正面": "Positive", "負面": "Negative", "中立": "Neutral"}[sentiment]
    labels = _labels_for_reason(signal_hits)
    impact_view = {
        "high": "高強度事件，可能明顯改變市場預期",
        "medium": "中等強度事件，對短期評價有一定影響",
        "low": "低強度或例行資訊，市場衝擊通常有限",
    }[event_severity]

    return (
        "Rule-Based Analysis:\n"
        f"- 事件類型：{event_type}；產業分類：{sector}。\n"
        f"- 偵測到的主要訊號：{labels}。\n"
        f"- 情緒判斷：{sentiment_label}，依方向性關鍵字與否定語境修正後判定。\n"
        f"- 影響力判斷：{impact_view}，impact score 為 {impact_score:.1f}。\n"
        f"- 信心程度：{confidence}。"
    )


def mock_analyze(
    title: str,
    content: Optional[str],
    stock_codes: list,
    keywords_only: bool = False,
) -> SentimentResult:
    """
    Rule-Based Financial Analyzer 入口。

    title 命中權重為 1.5 倍，content 命中權重為 1.0 倍。sentiment 回傳中文
    標籤（正面 / 負面 / 中立）以相容既有 dashboard 與資料表。
    """
    full_text = f"{title} {content or ''}"
    clean_text = _strip_negated_context(full_text)
    positive_score, positive_hits = _weighted_hits(title, content, POSITIVE_SIGNALS)
    negative_score, negative_hits = _weighted_hits(title, content, NEGATIVE_SIGNALS)
    signal_hits = positive_hits + negative_hits
    sentiment_score = positive_score + negative_score
    event_type = _classify_event_type(clean_text)
    sector = _classify_sector(clean_text)
    event_severity = _event_severity(clean_text, event_type, signal_hits)
    if LOSS_NARROWING_RE.search(full_text) and event_type not in {"financial_distress", "legal_risk"}:
        event_severity = "medium"
    confidence = _confidence(signal_hits, event_severity, event_type)

    if event_type == "routine_announcement" and not _has_strong_directional_signal(signal_hits):
        sentiment = "中立"
    elif sentiment_score >= 2:
        sentiment = "正面"
    elif sentiment_score <= -2:
        sentiment = "負面"
    else:
        sentiment = "中立"

    impact = _impact_score(
        text=full_text,
        signal_hits=signal_hits,
        event_type=event_type,
        sector=sector,
        event_severity=event_severity,
        confidence=confidence,
    )
    keywords = _standardize_keywords(full_text, signal_hits)
    reason = _build_reason(
        sentiment=sentiment,
        impact_score=impact,
        event_type=event_type,
        sector=sector,
        event_severity=event_severity,
        confidence=confidence,
        signal_hits=signal_hits,
    )

    return SentimentResult(
        sentiment=sentiment,
        impact_score=impact,
        reason=reason,
        keywords=keywords,
        raw_response="[RULE_BASED]",
    )


def _demo() -> None:
    examples = [
        {
            "name": "AI伺服器正面",
            "title": "AI伺服器需求爆發 台積電與輝達供應鏈重大訂單滿載",
            "content": "伺服器需求強勁，半導體供應鏈接單增加。",
        },
        {
            "name": "記憶體報價上漲",
            "title": "記憶體報價上揚 DRAM 供不應求",
            "content": "法人看好 HBM 與伺服器需求帶動價格上漲。",
        },
        {
            "name": "營收年減",
            "title": "電子廠公告營收年減 需求放緩",
            "content": "公司表示庫存去化仍需時間。",
        },
        {
            "name": "獲利下修",
            "title": "法人降評並獲利下修 毛利承壓",
            "content": "展望保守，需求疲弱影響下半年獲利。",
        },
        {
            "name": "退票財務危機",
            "title": "上市公司爆發退票與財務危機 恐有下市風險",
            "content": "市場擔憂違約風險升高，並可能面臨重大訴訟。",
        },
        {
            "name": "例行股東會",
            "title": "公司代子公司公告董事會決議召開股東會",
            "content": "本案屬例行資訊揭露，未涉及重大財務預測。",
        },
        {
            "name": "沒有砍單",
            "title": "供應鏈澄清沒有砍單 訂單維持穩定",
            "content": "公司表示未下修全年展望。",
        },
        {
            "name": "虧損收斂",
            "title": "生技公司虧損收斂 展望逐步改善",
            "content": "雖仍處虧損，但費用控制帶動虧損幅度縮小。",
        },
    ]

    for example in examples:
        result = mock_analyze(
            title=example["title"],
            content=example["content"],
            stock_codes=[],
        )
        print(f"=== {example['name']} ===")
        print(f"sentiment: {result.sentiment}")
        print(f"impact_score: {result.impact_score}")
        print(f"keywords: {', '.join(result.keywords)}")
        print(result.reason)
        print()


if __name__ == "__main__":
    _demo()
