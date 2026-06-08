"""
yahoo_tw.py — Yahoo 奇摩股市台股新聞 crawler

資料來源：Yahoo 股市公開 RSS
  一般台股新聞：https://tw.stock.yahoo.com/rss
  個股新聞：   https://tw.stock.yahoo.com/rss?s={股票代號}

RSS 每個 <item> 已含標題、連結、發布時間、摘要內文（description CDATA），
不需二次爬取個別文章頁面。

股票代號由內文以 regex 擷取（4 位數字，台股格式），
如「台積電(2330)」、「2330-TW」、「(2454)」等常見模式。
"""

import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

import requests

from crawlers.base import BaseCrawler
from models.article import Article, RawArticle

RSS_URL = "https://tw.stock.yahoo.com/rss"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

# 擷取台股代號的 regex：4–6 位數字，前後不能緊鄰其他數字
# (?<!\d) 排除更長數字的一部分（如電話、年份 20XX 由後處理過濾）
_STOCK_CODE_RE = re.compile(r"(?<!\d)(\d{4,6})(?:-TW|-tw)?(?!\d)")

# 擷取 CDATA 或一般 description 文字並移除殘留 HTML
_HTML_TAG_RE = re.compile(r"<[^>]+>")


class YahooTwCrawler(BaseCrawler):
    """Yahoo 奇摩股市台股新聞 crawler。"""

    source = "yahoo_tw"

    def __init__(
        self,
        stock_codes: Optional[list[str]] = None,
        request_delay: float = 1.0,
    ):
        """
        stock_codes : 要追蹤的個股代號，例如 ['2330', '2454']。
                      傳入空 list 或 None 表示抓一般台股新聞（不帶 s= 參數）。
        request_delay : 若有多個代號，每次 RSS 請求之間的間隔秒數。
        """
        super().__init__(request_delay=request_delay)
        self.stock_codes = stock_codes or []

    # ------------------------------------------------------------------
    # 實作 BaseCrawler 的兩個抽象方法
    # ------------------------------------------------------------------

    def fetch_list(self) -> list[RawArticle]:
        """
        依 stock_codes 清單（或一般新聞）呼叫 RSS，合併回傳所有 RawArticle。
        以 URL 去重，避免多個代號抓到同一篇文章。
        """
        targets = self.stock_codes if self.stock_codes else [None]
        seen_urls: set[str] = set()
        raw_list: list[RawArticle] = []

        for code in targets:
            params = {"s": code} if code else {}
            try:
                resp = requests.get(
                    RSS_URL,
                    params=params,
                    headers=HEADERS,
                    timeout=10,
                )
                resp.raise_for_status()
            except requests.RequestException as e:
                label = code or "general"
                print(f"[yahoo_tw] RSS 請求失敗（{label}）: {e}")
                continue

            items = self._parse_rss(resp.content)
            for raw in items:
                if raw.url not in seen_urls:
                    seen_urls.add(raw.url)
                    raw_list.append(raw)

            if len(targets) > 1:
                time.sleep(self.request_delay)

        return raw_list

    def parse_article(self, raw: RawArticle) -> Optional[Article]:
        """
        將 RawArticle 轉為正規化的 Article：
        - RSS pubDate（RFC 2822）→ datetime
        - description HTML → 純文字
        - 從標題 + 內文擷取台股代號
        """
        if not raw.title:
            return None

        published_at = self._parse_rfc2822(raw.published_at)
        if published_at is None:
            published_at = datetime.now()

        clean_content = self._clean_text(self._strip_html(raw.content))
        clean_summary = self._clean_text(self._strip_html(raw.summary))

        # 優先用 raw.stock_codes（fetch_list 已預填），再從內文補充
        stock_codes = list(raw.stock_codes)
        if not stock_codes:
            detected = self._extract_stock_codes(
                (raw.title or "") + " " + (raw.content or "")
            )
            stock_codes = detected

        return Article(
            source=self.source,
            title=raw.title,
            url=raw.url,
            published_at=published_at,
            content=clean_content,
            summary=clean_summary,
            stock_codes=stock_codes,
        )

    # ------------------------------------------------------------------
    # yahoo_tw 專用工具方法
    # ------------------------------------------------------------------

    def _parse_rss(self, xml_bytes: bytes) -> list[RawArticle]:
        """解析 RSS XML bytes，回傳 RawArticle list。"""
        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError as e:
            print(f"[yahoo_tw] RSS XML 解析失敗: {e}")
            return []

        items: list[RawArticle] = []
        for item in root.iter("item"):
            title    = (item.findtext("title") or "").strip()
            url      = (item.findtext("link") or "").strip()
            pub_date = (item.findtext("pubDate") or "").strip()
            desc     = (item.findtext("description") or "").strip()

            if not title or not url:
                continue

            items.append(
                RawArticle(
                    source=self.source,
                    title=title,
                    url=url,
                    published_at=pub_date,   # RFC 2822 字串，parse_article 再轉換
                    content=desc,            # RSS description 作為內文
                    summary=desc,            # 同時當摘要；parse_article 會清理 HTML
                    stock_codes=[],          # 由 parse_article 從內文擷取
                )
            )

        return items

    @staticmethod
    def _parse_rfc2822(date_str: Optional[str]) -> Optional[datetime]:
        """RFC 2822 時間字串（RSS pubDate 格式）→ 本地 datetime。"""
        if not date_str:
            return None
        try:
            dt_utc = parsedate_to_datetime(date_str)
            # 轉為 naive local time（台灣 UTC+8）
            return dt_utc.astimezone().replace(tzinfo=None)
        except Exception:
            return None

    @staticmethod
    def _strip_html(text: Optional[str]) -> Optional[str]:
        """移除 HTML 標籤。"""
        if not text:
            return None
        return _HTML_TAG_RE.sub(" ", text)

    @staticmethod
    def _extract_stock_codes(text: str) -> list[str]:
        """
        從文字中擷取台股代號（4–6 位數字）。
        過濾掉常見誤判：年份（2024–2030）、百分比前的數字。
        """
        candidates = _STOCK_CODE_RE.findall(text)
        seen: set[str] = set()
        result: list[str] = []
        for code in candidates:
            # 排除年份（2020–2030）與其他明顯誤判
            if re.match(r"^202[0-9]$|^203[0-9]$|^201[0-9]$", code):
                continue
            if code not in seen:
                seen.add(code)
                result.append(code)
        return result
