"""
Rule-Based Financial Analyzer

在不呼叫 Claude API 的情況下，使用財經關鍵字權重、事件類型與市場敏感度
產生 sentiment / impact_score / reason / keywords。保留 mock_analyze 函式名稱，
讓既有 pipeline 可以無痛改用 rule-based 分析結果。
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
    (r"營收創高|營收.*創.*高", 4.0, "營收創高", "營收表現"),
    (r"獲利成長|獲利.*成長|EPS.*成長", 4.0, "獲利成長", "獲利成長"),
    (r"優於預期|超乎預期|高於預期", 4.0, "優於預期", "獲利成長"),
    (r"外資買超", 3.0, "外資買超", "外資買超"),
    (r"訂單增加|接單增加|接單暢旺", 3.0, "訂單增加", "供應鏈"),
    (r"AI需求|AI.*需求", 3.0, "AI需求", "AI伺服器"),
    (r"伺服器需求|伺服器.*需求", 3.0, "伺服器需求", "AI伺服器"),
    (r"擴產|增產", 2.0, "擴產", "供應鏈"),
    (r"法說樂觀|法說.*樂觀", 2.0, "法說樂觀", "法說會"),
    (r"股利增加|配息增加|提高股利", 2.0, "股利增加", "股利政策"),
    (r"上修展望|上修.*展望|調升展望", 4.0, "上修展望", "獲利成長"),
    (r"毛利率改善|毛利.*改善", 3.0, "毛利率改善", "獲利成長"),
]

NEGATIVE_SIGNALS: list[tuple[str, float, str, str]] = [
    (r"獲利下修|下修.*獲利", -4.0, "獲利下修", "獲利下修"),
    (r"營收年減|營收.*年減", -3.0, "營收年減", "營收表現"),
    (r"虧損|轉虧", -4.0, "虧損", "財務風險"),
    (r"外資賣超", -3.0, "外資賣超", "外資賣超"),
    (r"砍單|訂單.*減少", -4.0, "砍單", "供應鏈"),
    (r"庫存過高|庫存.*過高", -3.0, "庫存過高", "庫存調整"),
    (r"毛利率下滑|毛利.*下滑", -3.0, "毛利率下滑", "獲利下修"),
    (r"裁員|減班休息", -3.0, "裁員", "財務風險"),
    (r"法說保守|法說.*保守", -2.0, "法說保守", "法說會"),
    (r"需求疲弱|需求.*疲弱", -3.0, "需求疲弱", "供應鏈"),
    (r"降評|調降評等|評等調降", -3.0, "降評", "獲利下修"),
    (r"退票", -4.0, "退票", "財務風險"),
    (r"財務危機|債務危機|違約", -5.0, "財務危機", "財務風險"),
    (r"訴訟|被告|求償|裁罰", -3.0, "訴訟", "訴訟風險"),
]

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
    ("financial_distress", r"退票|財務危機|債務危機|違約|資金缺口"),
    ("legal_risk", r"訴訟|被告|求償|裁罰|罰款"),
    ("foreign_investor", r"外資|買超|賣超"),
    ("ai_semiconductor", r"台積電|輝達|NVIDIA|AI|半導體|記憶體|HBM|伺服器"),
    ("guidance", r"上修|下修|展望|法說樂觀|法說保守|需求疲弱|降評"),
    ("earnings", r"財報|獲利|EPS|毛利率|盈餘"),
    ("revenue", r"營收|營收創高|營收年減|營收公布"),
    ("dividend", r"股利|配息|除權息"),
    ("macro_fx", r"匯率|台幣|新台幣|美元|Fed|聯準會|升息|降息"),
    ("supply_chain", r"供應鏈|砍單|接單|訂單|庫存|擴產"),
    ("routine_announcement", r"例行公告|公告|董事會|股東會|代子公司公告|例行資訊"),
]

MARKET_SENSITIVE_RE = re.compile(
    r"台積電|輝達|NVIDIA|AI|半導體|記憶體|HBM|DRAM|NAND|伺服器",
    re.IGNORECASE,
)
FINANCIAL_EVENT_RE = re.compile(r"財報|營收|獲利|法說會|EPS|毛利率")
FOREIGN_INVESTOR_RE = re.compile(r"外資買超|外資賣超")
SEVERE_NEGATIVE_RE = re.compile(r"下修|虧損|退票|財務危機|違約")
ROUTINE_RE = re.compile(r"例行公告|董事會|股東會|除權息")
SUBSIDIARY_RE = re.compile(r"代子公司公告")
COMPANY_INDUSTRY_RE = re.compile(
    r"\b\d{4}\b|台積電|聯發科|鴻海|台達電|廣達|緯創|華碩|技嘉|"
    r"AI|半導體|記憶體|伺服器|電子|金融|航運|鋼鐵|生技|電動車|供應鏈",
    re.IGNORECASE,
)

STANDARD_KEYWORDS: list[tuple[str, str]] = [
    (r"營收創高|營收年減|營收公布|營收", "營收表現"),
    (r"獲利成長|優於預期|毛利率改善|EPS", "獲利成長"),
    (r"獲利下修|下修|降評|毛利率下滑", "獲利下修"),
    (r"外資買超", "外資買超"),
    (r"外資賣超", "外資賣超"),
    (r"AI需求|AI伺服器|AI.*伺服器|伺服器.*AI|伺服器需求", "AI伺服器"),
    (r"半導體|台積電|晶圓|先進製程", "半導體"),
    (r"記憶體|HBM|DRAM|NAND", "記憶體"),
    (r"法說會|法說", "法說會"),
    (r"財報", "財報公布"),
    (r"股利|配息|除權息", "股利政策"),
    (r"匯率|台幣|新台幣|美元", "匯率影響"),
    (r"庫存|庫存過高", "庫存調整"),
    (r"供應鏈|訂單|接單|砍單|擴產", "供應鏈"),
    (r"財務危機|退票|違約|虧損|債務", "財務風險"),
    (r"訴訟|被告|求償|裁罰", "訴訟風險"),
    (r"例行公告|公告|董事會|股東會|代子公司公告|例行資訊", "例行公告"),
]


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
        in_title = bool(re.search(pattern, title, re.IGNORECASE))
        in_content = bool(body and re.search(pattern, body, re.IGNORECASE))

        if in_title:
            contribution += weight * 1.5
        if in_content:
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


def _has_strong_directional_signal(hits: list[dict]) -> bool:
    return any(abs(float(hit["base_weight"])) >= 3 for hit in hits)


def _impact_score(text: str, signal_hits: list[dict]) -> float:
    score = 3.0

    if MARKET_SENSITIVE_RE.search(text):
        score += 2.0
    if FINANCIAL_EVENT_RE.search(text):
        score += 1.5
    if FOREIGN_INVESTOR_RE.search(text):
        score += 1.0
    if SEVERE_NEGATIVE_RE.search(text):
        score += 2.0

    strong_hit_count = sum(1 for hit in signal_hits if abs(float(hit["base_weight"])) >= 3)
    if strong_hit_count >= 2:
        score += 1.0

    if ROUTINE_RE.search(text):
        score -= 1.5
    if SUBSIDIARY_RE.search(text):
        score -= 1.0
    if not COMPANY_INDUSTRY_RE.search(text):
        score -= 1.0

    return round(max(1.0, min(10.0, score)), 1)


def _standardize_keywords(text: str, signal_hits: list[dict]) -> list[str]:
    keywords: list[str] = []
    seen: set[str] = set()

    for hit in signal_hits:
        keyword = str(hit["keyword"])
        if keyword not in seen:
            keywords.append(keyword)
            seen.add(keyword)
        if len(keywords) >= 5:
            return keywords

    for pattern, keyword in STANDARD_KEYWORDS:
        if re.search(pattern, text, re.IGNORECASE) and keyword not in seen:
            keywords.append(keyword)
            seen.add(keyword)
        if len(keywords) >= 5:
            break

    if not keywords:
        keywords.append("例行公告" if re.search(r"公告|董事會|股東會", text) else "營收表現")

    return keywords[:5]


def _labels_for_reason(hits: list[dict], positive: bool) -> str:
    filtered = [
        hit for hit in hits
        if (float(hit["base_weight"]) > 0) == positive
    ]
    filtered.sort(key=lambda item: abs(float(item["contribution"])), reverse=True)
    labels = []
    seen = set()
    for hit in filtered:
        label = str(hit["label"])
        if label not in seen:
            labels.append(f"「{label}」")
            seen.add(label)
        if len(labels) >= 3:
            break
    return "、".join(labels)


def _build_reason(
    sentiment: str,
    impact_score: float,
    event_type: str,
    text: str,
    signal_hits: list[dict],
) -> str:
    sentiment_label = {"正面": "Positive", "負面": "Negative", "中立": "Neutral"}[sentiment]

    if sentiment == "正面":
        labels = _labels_for_reason(signal_hits, positive=True) or "正面財務訊號"
        first_line = f"偵測到{labels}等正面財務訊號。"
    elif sentiment == "負面":
        labels = _labels_for_reason(signal_hits, positive=False) or "負面營運訊號"
        first_line = f"偵測到{labels}等負面訊號。"
    else:
        if event_type == "routine_announcement":
            first_line = "內容主要屬於例行公告或資訊揭露。"
        else:
            first_line = "未偵測到明顯正面或負面財務訊號。"

    if MARKET_SENSITIVE_RE.search(text):
        impact_line = "新聞涉及 AI / 半導體等高市場敏感產業，因此提高 impact score。"
    elif event_type in {"financial_distress", "legal_risk"}:
        impact_line = "事件涉及財務或法律風險，可能影響市場對公司穩定性的評估。"
    elif event_type == "routine_announcement":
        impact_line = "內容偏例行資訊，市場衝擊通常較低。"
    else:
        impact_line = "事件與一般營運或財務資訊相關，impact score 依關鍵字強度調整。"

    if sentiment == "負面":
        middle_line = "該事件可能影響市場對公司未來獲利的預期。"
    elif sentiment == "正面":
        middle_line = "該事件可能改善市場對公司營收或獲利動能的預期。"
    else:
        middle_line = "目前缺乏足以改變市場預期的明確方向性訊號。"

    return (
        "Rule-Based Analysis:\n"
        f"- {first_line}\n"
        f"- {impact_line}\n"
        f"- {middle_line}\n"
        f"- 綜合判斷為 {sentiment_label}，impact score 為 {impact_score:.1f}。"
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
    positive_score, positive_hits = _weighted_hits(title, content, POSITIVE_SIGNALS)
    negative_score, negative_hits = _weighted_hits(title, content, NEGATIVE_SIGNALS)
    signal_hits = positive_hits + negative_hits
    sentiment_score = positive_score + negative_score
    event_type = _classify_event_type(full_text)

    if event_type == "routine_announcement" and not _has_strong_directional_signal(signal_hits):
        sentiment = "中立"
    elif sentiment_score >= 2:
        sentiment = "正面"
    elif sentiment_score <= -2:
        sentiment = "負面"
    else:
        sentiment = "中立"

    impact = _impact_score(full_text, signal_hits)
    keywords = _standardize_keywords(full_text, signal_hits)
    reason = _build_reason(
        sentiment=sentiment,
        impact_score=impact,
        event_type=event_type,
        text=full_text,
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
            "name": "正面財報",
            "title": "台積電財報優於預期 營收創高且毛利率改善",
            "content": "公司表示 AI需求與伺服器需求強勁，帶動獲利成長。",
        },
        {
            "name": "負面下修",
            "title": "電子零組件廠獲利下修 需求疲弱且庫存過高",
            "content": "法人同步降評，預期毛利率下滑壓力延續。",
        },
        {
            "name": "AI半導體",
            "title": "AI伺服器需求升溫 半導體供應鏈訂單增加",
            "content": "輝達 NVIDIA 新平台帶動記憶體與伺服器相關廠商接單增加。",
        },
        {
            "name": "例行公告",
            "title": "公司代子公司公告董事會決議召開股東會",
            "content": "本案屬例行資訊揭露，未涉及重大財務預測。",
        },
        {
            "name": "財務危機",
            "title": "上市公司爆發退票與財務危機 恐面臨訴訟",
            "content": "市場擔憂債務違約風險升高，營運資金出現缺口。",
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
