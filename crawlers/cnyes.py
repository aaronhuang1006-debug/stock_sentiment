"""
cnyes.py — 鉅亨網台股新聞 crawler

資料來源：鉅亨網公開 JSON API
  清單：https://api.cnyes.com/media/api/v1/newslist/category/tw_stock
  文章頁：https://news.cnyes.com/news/id/{newsId}

鉅亨 API 已在清單回應中包含完整內文（HTML 格式），
因此不需要另外爬取個別文章頁面，一次請求即可取得所有欄位。
"""

import html
import re
import time
from datetime import datetime, timezone
from typing import Optional

import requests

from crawlers.base import BaseCrawler
from models.article import Article, RawArticle

# 台股新聞清單 API，limit 最大約 30
LIST_URL = "https://api.cnyes.com/media/api/v1/newslist/category/tw_stock"

# 文章永久連結格式
ARTICLE_URL = "https://news.cnyes.com/news/id/{news_id}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


class CnyesCrawler(BaseCrawler):
    """鉅亨網台股新聞 crawler。"""

    source = "cnyes"

    def __init__(self, limit: int = 30, request_delay: float = 1.0):
        """
        limit         : 每次爬取的最大筆數（API 上限約 30）
        request_delay : 請求間隔秒數
        """
        super().__init__(request_delay=request_delay)
        self.limit = limit

    # ------------------------------------------------------------------
    # 實作 BaseCrawler 的兩個抽象方法
    # ------------------------------------------------------------------

    def fetch_list(self) -> list[RawArticle]:
        """
        呼叫鉅亨 API，取得台股新聞清單。
        API 已包含完整 content，直接組成 RawArticle，不需二次請求。
        """
        try:
            resp = requests.get(
                LIST_URL,
                params={"limit": self.limit},
                headers=HEADERS,
                timeout=10,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"[cnyes] API 請求失敗: {e}")
            return []

        items = resp.json().get("items", {}).get("data", [])

        raw_list: list[RawArticle] = []
        for item in items:
            news_id = item.get("newsId")
            if not news_id:
                continue

            raw_list.append(
                RawArticle(
                    source=self.source,
                    title=item.get("title", "").strip(),
                    url=ARTICLE_URL.format(news_id=news_id),
                    # publishAt 是 Unix timestamp（秒），轉為 ISO8601 字串暫存
                    published_at=str(item.get("publishAt", "")),
                    # content 是 HTML，parse_article 負責清理
                    content=item.get("content", ""),
                    summary=item.get("summary", ""),
                    # stock 欄位已是代號列表，如 ['2330', '2317']
                    stock_codes=item.get("stock") or [],
                )
            )

            time.sleep(self.request_delay * 0.1)  # API 模式只需極短間隔

        return raw_list

    def parse_article(self, raw: RawArticle) -> Optional[Article]:
        """
        將 RawArticle 轉為正規化的 Article：
        - Unix timestamp → datetime
        - HTML content → 純文字
        """
        # 標題為空視為無效資料
        if not raw.title:
            return None

        # 轉換發布時間：Unix timestamp 字串 → datetime（台北時間 UTC+8）
        published_at = self._parse_unix_timestamp(raw.published_at)
        if published_at is None:
            published_at = datetime.now()  # 無法解析時用爬取當下時間代替

        # 清理 HTML 內文
        clean_content = self._strip_html(raw.content)

        return Article(
            source=self.source,
            title=raw.title,
            url=raw.url,
            published_at=published_at,
            content=self._clean_text(clean_content),
            summary=self._clean_text(raw.summary),
            stock_codes=raw.stock_codes,
        )

    # ------------------------------------------------------------------
    # cnyes 專用的工具方法
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_unix_timestamp(ts_str: Optional[str]) -> Optional[datetime]:
        """Unix timestamp 字串（秒）→ datetime（本地時間）。"""
        if not ts_str:
            return None
        try:
            ts = int(ts_str)
            # fromtimestamp 會自動轉成本機時區（台灣執行即為 UTC+8）
            return datetime.fromtimestamp(ts)
        except (ValueError, OSError):
            return None

    @staticmethod
    def _strip_html(html_text: Optional[str]) -> Optional[str]:
        """移除 HTML 標籤，並還原 HTML entities（如 &amp; → &）。"""
        if not html_text:
            return None
        # 先 unescape HTML entities（&lt; → <、&amp; → &）
        text = html.unescape(html_text)
        # 再移除所有 HTML 標籤
        text = re.sub(r"<[^>]+>", " ", text)
        return text
