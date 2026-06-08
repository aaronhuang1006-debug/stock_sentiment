"""
ctee.py — 工商時報證券新聞 crawler.

工商時報 /feed 目前回傳 404，因此使用公開證券即時列表：
  https://www.ctee.com.tw/livenews/stock

列表頁已包含標題與文章連結；若未來頁面改成動態渲染或 HTML 結構改版，
crawler 會記錄失敗原因並回傳空列表，不會中斷整個 pipeline。
"""

import re
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from crawlers.base import BaseCrawler
from crawlers.rss_utils import HEADERS, extract_stock_codes, parse_feed_datetime, strip_html
from models.article import Article, RawArticle

LIST_URL = "https://www.ctee.com.tw/livenews/stock"


class CteeCrawler(BaseCrawler):
    """工商時報證券新聞列表 crawler."""

    source = "ctee"

    def __init__(self, limit: int = 30, request_delay: float = 1.0, timeout: int = 10):
        super().__init__(request_delay=request_delay)
        self.limit = limit
        self.timeout = timeout

    def fetch_list(self) -> list[RawArticle]:
        try:
            resp = requests.get(LIST_URL, headers=HEADERS, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"[ctee] 列表頁請求失敗: {e}")
            return []

        try:
            soup = BeautifulSoup(resp.text, "html.parser")
        except Exception as e:
            print(f"[ctee] HTML 解析失敗: {e}")
            return []

        raw_list: list[RawArticle] = []
        seen_urls: set[str] = set()
        for link in soup.find_all("a", href=True):
            title = " ".join(link.get_text(" ", strip=True).split())
            href = link.get("href", "").strip()
            if not title or len(title) < 8 or "/news/" not in href:
                continue

            url = urljoin("https://www.ctee.com.tw/", href)
            if url in seen_urls:
                continue
            seen_urls.add(url)

            raw_list.append(
                RawArticle(
                    source=self.source,
                    title=title,
                    url=url,
                    published_at=self._date_from_url(url),
                    content=title,
                    summary=title,
                    stock_codes=[],
                )
            )
            if len(raw_list) >= self.limit:
                break

        print(f"[ctee] 列表頁抓到 {len(raw_list)} 篇")
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
    def _date_from_url(url: str) -> Optional[str]:
        match = re.search(r"/news/(20\d{6})", url)
        if not match:
            return None
        raw = match.group(1)
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
