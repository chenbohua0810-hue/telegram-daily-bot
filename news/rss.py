import logging
from dataclasses import dataclass

import feedparser
import httpx

logger = logging.getLogger(__name__)

RSS_SOURCES = [
    'https://news.ltn.com.tw/rss/all.xml',
    'https://feeds.feedburner.com/rsscna',
    'https://feeds.bbci.co.uk/zhongwen/trad/rss.xml',
    'https://news.google.com/rss?hl=zh-TW&gl=TW&ceid=TW:zh-Hant',
]


@dataclass(frozen=True)
class NewsItem:
    title: str
    url: str
    summary: str
    source: str


def _parse_feed(raw_xml: str, feed_url: str, limit: int) -> list[NewsItem]:
    feed = feedparser.parse(raw_xml)
    items: list[NewsItem] = []
    for entry in feed.entries[:limit]:
        summary = getattr(entry, 'summary', '') or ''
        items.append(
            NewsItem(
                title=entry.title,
                url=entry.link,
                summary=summary[:200],
                source=feed_url,
            )
        )
    return items


async def fetch_rss_news(feed_url: str, limit: int = 5) -> list[NewsItem]:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(feed_url)
        resp.raise_for_status()
    return _parse_feed(resp.text, feed_url, limit)


async def fetch_all_sources(limit_per_source: int = 3) -> list[NewsItem]:
    import asyncio

    all_items: list[NewsItem] = []

    async def _fetch_one(url: str) -> list[NewsItem]:
        try:
            return await fetch_rss_news(url, limit=limit_per_source)
        except Exception as exc:
            logger.warning('Failed to fetch RSS from %s: %s', url, exc)
            return []

    results = await asyncio.gather(*[_fetch_one(url) for url in RSS_SOURCES])
    for items in results:
        all_items.extend(items)

    return all_items
