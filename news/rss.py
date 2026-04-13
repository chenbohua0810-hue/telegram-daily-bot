from dataclasses import dataclass

import feedparser

RSS_SOURCES = [
    'https://news.ltn.com.tw/rss/all.xml',
    'https://feeds.feedburner.com/rsscna',
    'https://feeds.bbci.co.uk/zhongwen/trad/rss.xml',
    'https://news.google.com/rss?hl=zh-TW&gl=TW&ceid=TW:zh-Hant',
]


@dataclass
class NewsItem:
    title: str
    url: str
    summary: str
    source: str


def fetch_rss_news(feed_url: str, limit: int = 5) -> list[NewsItem]:
    feed = feedparser.parse(feed_url)
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


def fetch_all_sources(limit_per_source: int = 3) -> list[NewsItem]:
    all_items: list[NewsItem] = []

    for url in RSS_SOURCES:
        try:
            items = fetch_rss_news(url, limit=limit_per_source)
            all_items.extend(items)
        except Exception:
            continue

    return all_items
