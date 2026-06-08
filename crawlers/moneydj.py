"""
moneydj.py — MoneyDJ 台股新聞 crawler.

MoneyDJ 沒有穩定公開 RSS 被明確列在站上，因此先使用手機版台股列表：
  https://m.moneydj.com/newsList.aspx?a=MB06

若頁面改成 JS 動態渲染、加上阻擋或 HTML 結構改版，本 crawler 會在
try/except 中記錄原因並回傳空列表；需要時可再補二階段文章頁解析。
"""

from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from crawlers.base import BaseCrawler
from crawlers.rss_utils import HEADERS, extract_stock_codes, parse_feed_datetime, strip_html
from models.article import Article, RawArticle

LIST_URL = "https://m.moneydj.com/newsList.aspx?a=MB06"


class MoneyDjCrawler(BaseCrawler):
    """MoneyDJ 台股新聞列表 crawler."""

    source = "moneydj"

    def __init__(self, limit: int = 30, request_delay: float = 1.0, timeout: int = 10):
        super().__init__(request_delay=request_delay)
        self.limit = limit
        self.timeout = timeout

    def fetch_list(self) -> list[RawArticle]:
        try:
            resp = requests.get(LIST_URL, headers=HEADERS, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"[moneydj] 列表頁請求失敗: {e}")
            return []

        try:
            soup = BeautifulSoup(resp.text, "html.parser")
        except Exception as e:
            print(f"[moneydj] HTML 解析失敗: {e}")
            return []

        raw_list: list[RawArticle] = []
        seen_urls: set[str] = set()

        for link in soup.find_all("a", href=True):
            title = " ".join(link.get_text(" ", strip=True).split())
            href = link.get("href", "").strip()
            if not title or len(title) < 8:
                continue
            if "f1a.aspx" not in href.lower():
                continue

            url = urljoin("https://m.moneydj.com/", href)
            if url in seen_urls:
                continue
            seen_urls.add(url)

            parent_text = " ".join((link.parent.get_text(" ", strip=True) if link.parent else title).split())
            raw_list.append(
                RawArticle(
                    source=self.source,
                    title=title,
                    url=url,
                    published_at=self._guess_datetime(parent_text),
                    content=parent_text,
                    summary=parent_text,
                    stock_codes=[],
                )
            )
            if len(raw_list) >= self.limit:
                break

        print(f"[moneydj] 列表頁抓到 {len(raw_list)} 篇")
        return raw_list

    def parse_article(self, raw: RawArticle) -> Optional[Article]:
        if not raw.title or not raw.url:
            return None
        published_at = parse_feed_datetime(raw.published_at) or datetime.now()
        content = self._clean_text(strip_html(raw.content))
        summary = self._clean_text(strip_html(raw.summary))
        stock_codes = extract_stock_codes(" ".join([raw.title, raw.content or "", raw.summary or ""]))

        return Article(
            source=self.source,
            title=raw.title,
            url=raw.url,
            published_at=published_at,
            content=content,
            summary=summary,
            stock_codes=stock_codes,
        )

    @staticmethod
    def _guess_datetime(text: str) -> Optional[str]:
        # MoneyDJ 列表常把時間放在標題附近；若抓不到，parse_article 會用 now。
        import re

        match = re.search(r"(20\d{2}[/-]\d{1,2}[/-]\d{1,2}(?:\s+\d{1,2}:\d{2})?)", text)
        return match.group(1) if match else None
