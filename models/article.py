"""
article.py — 定義新聞文章的資料結構

RawArticle : crawler 爬回來的原始資料（格式不統一）
Article    : 經過 normalizer 處理後的統一格式，對應資料庫欄位
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class RawArticle:
    """
    各 crawler 爬回來的原始資料。
    欄位盡量寬鬆，允許 None，因為不同來源的格式不同。
    """
    source: str                        # 來源識別碼，如 'cnyes'、'yahoo_tw'
    title: str                         # 新聞標題
    url: str                           # 原始連結
    published_at: Optional[str] = None # 發布時間（字串，格式各來源不同）
    content: Optional[str] = None      # 新聞內文
    summary: Optional[str] = None      # 副標或摘要（部分來源有）
    stock_codes: list[str] = field(default_factory=list)  # 相關股票代號，如 ['2330']


@dataclass
class Article:
    """
    正規化後的統一格式，直接對應 SQLite 的 articles 資料表。
    AI 分析欄位（sentiment、impact_score、reason）預設為 None，
    等 Claude API 分析完再透過 db.update_sentiment() 填入。
    """
    source: str                         # 來源識別碼
    title: str                          # 新聞標題
    url: str                            # 原始連結（UNIQUE，用於第一層去重）
    published_at: datetime              # 發布時間（已轉為 datetime 物件）
    content: Optional[str] = None       # 新聞內文
    summary: Optional[str] = None       # 摘要

    # 股票代號列表，存入 DB 時序列化為 JSON 字串，如 '["2330","2317"]'
    stock_codes: list[str] = field(default_factory=list)

    # content_hash：由 title + content 前 300 字計算，用於第三層去重
    content_hash: Optional[str] = None

    # --- AI 分析結果（爬蟲階段為 None，分析後填入）---
    sentiment: Optional[str] = None     # 情緒標籤：'正面' / '負面' / '中立'
    impact_score: Optional[float] = None  # 影響力 / 信心分數，0.0–100.0
    reason: Optional[str] = None        # Claude 的判斷理由
    keywords: list = field(default_factory=list)  # 市場關鍵字，如 ["AI晶片","CoWoS"]

    # 爬取時間（由程式自動填入，不需要 crawler 提供）
    crawled_at: datetime = field(default_factory=datetime.now)
