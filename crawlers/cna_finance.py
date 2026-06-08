"""
cna_finance.py — 中央社財經 / 產經證券 RSS crawler.

官方 RSS 列表：
  https://www.cna.com.tw/about/rss.aspx
財經 feed:
  https://feeds.feedburner.com/rsscna/finance
"""

from crawlers.rss_utils import RssCrawler


class CnaFinanceCrawler(RssCrawler):
    """中央社產經證券 RSS crawler."""

    source = "cna_finance"
    feed_urls = ["https://feeds.feedburner.com/rsscna/finance"]
