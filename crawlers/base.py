"""
base.py — 所有 crawler 的抽象基底類別

每個新來源只需繼承 BaseCrawler，實作兩個方法：
  1. fetch_list()     → 抓新聞清單，回傳 list[RawArticle]
  2. parse_article()  → 將一筆 RawArticle 轉為正規化的 Article

run() 是模板方法，固定流程：fetch → parse → hash → 回傳，
子類別不需要也不應該覆寫 run()。
"""

import hashlib
import re
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from models.article import Article, RawArticle


class BaseCrawler(ABC):
    """
    所有 crawler 的父類別。

    子類別必須定義：
        source = "cnyes"   # 來源識別碼（字串常數）

    子類別必須實作：
        fetch_list()
        parse_article()
    """

    # 子類別必須覆寫這個屬性，例如 source = "cnyes"
    source: str = ""

    def __init__(self, request_delay: float = 1.0):
        """
        request_delay : 每次 HTTP 請求之間的間隔秒數，避免對目標網站造成負擔。
        """
        if not self.source:
            raise NotImplementedError(f"{self.__class__.__name__} 必須定義 source 屬性")
        self.request_delay = request_delay

    # ------------------------------------------------------------------
    # 子類別必須實作的抽象方法
    # ------------------------------------------------------------------

    @abstractmethod
    def fetch_list(self) -> list[RawArticle]:
        """
        抓取新聞清單頁，回傳原始資料列表。
        每筆至少要有 title 和 url，其餘欄位可為 None。
        """
        ...

    @abstractmethod
    def parse_article(self, raw: RawArticle) -> Optional[Article]:
        """
        將一筆 RawArticle 轉為正規化的 Article。
        若解析失敗（例如頁面結構改版），回傳 None，run() 會自動略過。
        """
        ...

    # ------------------------------------------------------------------
    # 模板方法：固定流程，子類別不需覆寫
    # ------------------------------------------------------------------

    def run(self) -> list[Article]:
        """
        執行完整爬取流程：
        1. fetch_list()  取得原始清單
        2. parse_article() 逐筆正規化
        3. compute_hash() 計算去重用的 content_hash
        4. 回傳 list[Article] 給 CrawlerManager

        任何單筆文章的例外不會中斷整批，只印出警告後略過。
        """
        print(f"[{self.source}] 開始爬取...")
        raw_list = self.fetch_list()
        print(f"[{self.source}] 取得 {len(raw_list)} 筆原始資料")

        articles: list[Article] = []
        for raw in raw_list:
            try:
                article = self.parse_article(raw)
                if article is None:
                    continue
                # 計算 content_hash，供第三層去重使用
                article.content_hash = self._compute_hash(article.title, article.content)
                articles.append(article)
            except Exception as e:
                print(f"[{self.source}] 解析失敗，略過 ({raw.url}): {e}")

        print(f"[{self.source}] 正規化完成，共 {len(articles)} 筆")
        return articles

    # ------------------------------------------------------------------
    # 共用工具方法（子類別可直接呼叫）
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_hash(title: str, content: Optional[str]) -> str:
        """
        計算 content_hash：移除所有空白後，取 title + content 前 300 字做 SHA-256。
        用於第三層去重，過濾跨來源的完全相同內文。
        """
        text = re.sub(r"\s+", "", title + (content or "")[:300])
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _parse_datetime(raw_time: Optional[str], fmt: str) -> Optional[datetime]:
        """
        將字串時間轉為 datetime，解析失敗回傳 None。
        fmt 範例：'%Y-%m-%d %H:%M:%S' 或 '%Y/%m/%d'

        各 crawler 可以直接呼叫這個方法，不用自己寫 try/except。
        """
        if not raw_time:
            return None
        try:
            return datetime.strptime(raw_time.strip(), fmt)
        except ValueError:
            return None

    @staticmethod
    def _clean_text(text: Optional[str]) -> Optional[str]:
        """移除多餘的空白與換行，讓內文格式一致。"""
        if not text:
            return None
        return re.sub(r"\s+", " ", text).strip()
