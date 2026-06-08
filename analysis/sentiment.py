"""
sentiment.py — 使用 Claude API 分析台股新聞情緒

輸入：標題 + 內文 + 股票代號
輸出：SentimentResult（sentiment / impact_score / reason）

impact_score 依 impact_score_guideline.md 評分（1–10 整數）。
reason 必須點出四個維度中哪幾項是主要加分因素：
  - 公司規模、獲利影響、市場影響、指數影響
"""

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import anthropic

# ── 載入 .env（本機開發用；Cloud 上 .env 不存在時靜默略過）──
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv()
except ImportError:
    pass


def _resolve_api_key() -> str:
    """
    API key 載入順序（優先順序由高到低）：
      1. Streamlit st.secrets["ANTHROPIC_API_KEY"]  — Streamlit Cloud 部署時
      2. 環境變數 ANTHROPIC_API_KEY                  — 本機 .env 或系統環境
    回傳空字串表示未設定任何 key。
    """
    # 1. Streamlit secrets（僅在 Streamlit runtime 中有效）
    try:
        import streamlit as st
        key = st.secrets.get("ANTHROPIC_API_KEY", "")
        if key and key.strip():
            return key.strip()
    except Exception:
        pass

    # 2. 環境變數
    return os.environ.get("ANTHROPIC_API_KEY", "").strip()

VALID_SENTIMENTS = {"正面", "負面", "中立"}

# guideline 檔案路徑（相對於本檔案的專案根目錄）
_GUIDELINE_PATH = Path(__file__).parent.parent / "impact_score_guideline.md"

_SYSTEM_PROMPT_TEMPLATE = """\
你是台股新聞情緒分析師。

## 情緒標籤定義
- 正面：利多消息、業績成長、重大得標、產品突破、法人調升評等等
- 負面：業績衰退、裁員、訴訟、法人調降、供應鏈中斷、重大虧損等
- 中立：例行公告、人事異動（無明確影響）、一般市場資訊等

## Impact Score 評分準則
請嚴格依照以下準則為新聞評分（1–10 整數）：

{guideline}

## 評分流程
在決定 impact_score 之前，請依序評估以下四個維度，並在 reason 中點出
哪幾項是這篇新聞的主要加分原因：

1. **公司規模**：涉及公司的市值與台股權重（大型權值股 vs. 中小型）
2. **獲利影響**：對未來營收或 EPS 的改變幅度與確定性（有無具體數字）
3. **市場影響**：是否為罕見、不可逆或結構性事件（vs. 例行公告）
4. **指數影響**：是否可能帶動台股加權指數或特定族群大幅波動

## Keywords 關鍵字
請從新聞中萃取 3–5 個最能代表市場意義的關鍵字或短語，優先選擇：
- 產品 / 技術名稱（如 CoWoS、HBM、ASIC、液冷散熱）
- 產業趨勢（如 AI伺服器、邊緣運算、電動車）
- 事件類型（如 法說會、獲利下修、庫存去化、漲價）
- 供應鏈位置（如 晶圓代工、封測、PCB）
請避免選過於通用的詞（如「股價」「台灣」「公司」）。

## 輸出格式
嚴格以 JSON 回覆，不要加任何 markdown 或多餘文字：
{{
  "sentiment": "正面" | "負面" | "中立",
  "impact_score": 1 到 10 的整數,
  "keywords": ["關鍵字1", "關鍵字2", "關鍵字3"],
  "reason": "說明判斷理由，並明確點出四個維度（公司規模／獲利影響／市場影響／指數影響）中哪幾項是主要加分原因"
}}\
"""


def _load_system_prompt() -> str:
    """載入 guideline 並嵌入 system prompt；檔案不存在時拋出清楚錯誤。"""
    if not _GUIDELINE_PATH.exists():
        raise FileNotFoundError(
            f"[錯誤] 找不到評分準則檔案：{_GUIDELINE_PATH}\n"
            "請確認專案根目錄下有 impact_score_guideline.md。"
        )
    guideline = _GUIDELINE_PATH.read_text(encoding="utf-8")
    return _SYSTEM_PROMPT_TEMPLATE.format(guideline=guideline)


@dataclass
class SentimentResult:
    """Claude API 回傳的情緒分析結果。"""
    sentiment: str              # '正面' / '負面' / '中立'
    impact_score: float         # 1.0–10.0（對應 articles.impact_score 欄位，REAL 型別）
    reason: str                 # 判斷理由
    keywords: list = None       # 市場關鍵字，3–5 個，如 ["AI晶片","CoWoS"]
    raw_response: str = ""      # 原始 Claude 回應（debug 用）

    def __post_init__(self) -> None:
        if self.keywords is None:
            self.keywords = []


class SentimentAnalyzer:
    """
    封裝 Claude API 情緒分析邏輯。

    使用範例：
        analyzer = SentimentAnalyzer()
        result = analyzer.analyze(title, content, stock_codes)

    初始化時若找不到 ANTHROPIC_API_KEY，立即拋出 EnvironmentError（不等到呼叫時才失敗）。
    """

    MODEL = "claude-opus-4-8"

    def __init__(self) -> None:
        api_key = _resolve_api_key()
        if not api_key:
            raise EnvironmentError(
                "\n[錯誤] 找不到 ANTHROPIC_API_KEY。\n"
                "載入順序：\n"
                "  1. Streamlit Cloud：Settings → Secrets → ANTHROPIC_API_KEY\n"
                "  2. 本機 .env 檔案（複製 .env.example → .env 並填入金鑰）\n"
                "  3. 系統環境變數：export ANTHROPIC_API_KEY='sk-ant-...'\n"
                "若只需要 Rule-Based 分析，可改用 --mock-analysis 模式，無需 API key。"
            )
        self._client = anthropic.Anthropic(api_key=api_key)
        # 在初始化時就載入並組裝 system prompt，讓檔案不存在的錯誤提早暴露
        self._system_prompt = _load_system_prompt()

    def analyze(
        self,
        title: str,
        content: Optional[str],
        stock_codes: list[str],
    ) -> SentimentResult:
        """
        分析單篇新聞的情緒。

        :param title:       新聞標題
        :param content:     新聞內文（可為 None）
        :param stock_codes: 相關股票代號列表，如 ['2330']
        :returns:           SentimentResult
        :raises ValueError: 若 Claude 回傳的 JSON 格式無法解析
        """
        user_message = self._build_user_message(title, content, stock_codes)

        with self._client.messages.stream(
            model=self.MODEL,
            max_tokens=1024,
            thinking={"type": "adaptive"},
            system=self._system_prompt,
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            final = stream.get_final_message()

        raw = ""
        for block in final.content:
            if block.type == "text":
                raw = block.text
                break

        return self._parse_response(raw)

    # ------------------------------------------------------------------
    # 內部工具方法
    # ------------------------------------------------------------------

    @staticmethod
    def _build_user_message(
        title: str, content: Optional[str], stock_codes: list[str]
    ) -> str:
        lines = []
        if stock_codes:
            lines.append(f"相關股票：{', '.join(stock_codes)}")
        lines.append(f"標題：{title}")
        if content:
            lines.append(f"內文：{content[:1500]}")
        return "\n".join(lines)

    @staticmethod
    def _parse_response(raw: str) -> SentimentResult:
        """解析 Claude 回傳的 JSON，回傳 SentimentResult。"""
        # 去掉可能存在的 markdown code fence
        cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Claude 回傳的 JSON 無法解析: {e}\n原始內容: {raw!r}"
            ) from e

        sentiment = str(data.get("sentiment", "")).strip()
        if sentiment not in VALID_SENTIMENTS:
            raise ValueError(
                f"無效的情緒標籤: {sentiment!r}，原始回應: {raw!r}"
            )

        try:
            impact_score = float(data["impact_score"])
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(
                f"impact_score 格式錯誤: {e}\n原始回應: {raw!r}"
            ) from e

        # 夾緊到 1–10
        impact_score = max(1.0, min(10.0, impact_score))
        reason = str(data.get("reason", "")).strip()

        # keywords：容錯解析，格式不對就給空列表，不拋例外
        raw_kw = data.get("keywords", [])
        if isinstance(raw_kw, list):
            keywords = [str(k).strip() for k in raw_kw if str(k).strip()][:5]
        else:
            keywords = []

        return SentimentResult(
            sentiment=sentiment,
            impact_score=impact_score,
            reason=reason,
            keywords=keywords,
            raw_response=raw,
        )
