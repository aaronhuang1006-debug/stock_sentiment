"""
rss_utils.py — shared helpers for RSS/list based financial news crawlers.

The helpers keep new source crawlers small and consistent:
- requests always use timeout and headers
- RSS parsing is centralized
- output is normalized through RawArticle/Article
"""

import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Optional

import requests

from crawlers.base import BaseCrawler
from models.article import Article, RawArticle

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, text/html, */*",
}

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_STOCK_CODE_RE = re.compile(r"(?<!\d)(\d{4,6})(?:-TW|-tw)?(?!\d)")


def strip_html(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    return _HTML_TAG_RE.sub(" ", text)


def parse_feed_datetime(date_str: Optional[str]) -> Optional[datetime]:
    if not date_str:
        return None
    raw = date_str.strip()
    for parser in (
        parsedate_to_datetime,
        lambda v: datetime.fromisoformat(v.replace("Z", "+00:00")),
    ):
        try:
            dt = parser(raw)
            if getattr(dt, "tzinfo", None) is not None:
                return dt.astimezone().replace(tzinfo=None)
            return dt
        except Exception:
            continue

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y-%m-%d", "%Y/%m/%d"):
        parsed = BaseCrawler._parse_datetime(raw, fmt)
        if parsed:
            return parsed
    return None


def extract_stock_codes(text: str) -> list[str]:
    candidates = _STOCK_CODE_RE.findall(text or "")
    seen: set[str] = set()
    result: list[str] = []
    for code in candidates:
        if re.match(r"^20[12][0-9]$|^203[0-9]$", code):
            continue
        if code not in seen:
            seen.add(code)
            result.append(code)
    return result


class RssCrawler(BaseCrawler):
    """Base implementation for sources that expose one or more RSS feeds."""

    feed_urls: list[str] = []
    limit: int = 30
    timeout: int = 10

    def __init__(self, limit: int = 30, request_delay: float = 1.0, timeout: int = 10):
        super().__init__(request_delay=request_delay)
        self.limit = limit
        self.timeout = timeout

    def fetch_list(self) -> list[RawArticle]:
        seen_urls: set[str] = set()
        raw_list: list[RawArticle] = []

        for feed_url in self.feed_urls:
            try:
                resp = requests.get(feed_url, headers=HEADERS, timeout=self.timeout)
                resp.raise_for_status()
            except requests.RequestException as e:
                print(f"[{self.source}] RSS 請求失敗 ({feed_url}): {e}")
                continue

            items = self._parse_rss(resp.content)
            print(f"[{self.source}] feed {feed_url} 抓到 {len(items)} 篇")
            for raw in items:
                if raw.url in seen_urls:
                    continue
                seen_urls.add(raw.url)
                raw_list.append(raw)
                if len(raw_list) >= self.limit:
                    return raw_list
            time.sleep(self.request_delay)

        return raw_list

    def parse_article(self, raw: RawArticle) -> Optional[Article]:
        if not raw.title or not raw.url:
            return None

        published_at = parse_feed_datetime(raw.published_at) or datetime.now()
        content = self._clean_text(strip_html(raw.content))
        summary = self._clean_text(strip_html(raw.summary))
        stock_codes = raw.stock_codes or extract_stock_codes(
            " ".join([raw.title or "", raw.content or "", raw.summary or ""])
        )

        return Article(
            source=self.source,
            title=raw.title,
            url=raw.url,
            published_at=published_at,
            content=content,
            summary=summary,
            stock_codes=stock_codes,
        )

    def _parse_rss(self, xml_bytes: bytes) -> list[RawArticle]:
        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError as e:
            print(f"[{self.source}] RSS XML 解析失敗: {e}")
            return []

        items: list[RawArticle] = []
        for item in root.iter("item"):
            title = self._node_text(item, "title")
            url = self._node_text(item, "link")
            pub_date = self._node_text(item, "pubDate") or self._node_text(item, "updated")
            desc = self._node_text(item, "description")

            if not title or not url:
                continue

            items.append(
                RawArticle(
                    source=self.source,
                    title=title,
                    url=url,
                    published_at=pub_date,
                    content=desc,
                    summary=desc,
                    stock_codes=[],
                )
            )
        return items

    @staticmethod
    def _node_text(item: ET.Element, tag_name: str) -> str:
        for child in item:
            if child.tag.split("}")[-1] == tag_name:
                return (child.text or "").strip()
        return ""
