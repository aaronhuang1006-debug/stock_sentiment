"""
money_udn.py — 經濟日報 crawler.

經濟日報公開頁面可能因分類與會員策略調整而變動。此 crawler 先使用
RSS candidate；若回應不是 RSS 或網站調整，會安全回傳空列表並在 log
中顯示原因，不影響其他來源。
"""

from crawlers.rss_utils import RssCrawler


class MoneyUdnCrawler(RssCrawler):
    """經濟日報 RSS crawler."""

    source = "money_udn"
    feed_urls = [
        "https://money.udn.com/rssfeed/news/1001/5591",
        "https://money.udn.com/rssfeed/news/1001/5588",
    ]
