from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import html
import re
import urllib.request
import xml.etree.ElementTree as ET


AI_KEYWORDS = (
    "ai",
    "artificial intelligence",
    "openai",
    "anthropic",
    "gemini",
    "llm",
    "large language model",
    "agent",
    "nvidia",
    "gpu",
    "machine learning",
    "deepmind",
)
TECH_KEYWORDS = (
    "chip",
    "semiconductor",
    "cloud",
    "security",
    "cyber",
    "developer",
    "startup",
    "robot",
    "software",
    "apple",
    "google",
    "microsoft",
    "meta",
)


@dataclass(frozen=True)
class NewsItem:
    title: str
    link: str
    source: str
    published_at: datetime | None
    summary: str


def fetch_news_items(rss_urls: tuple[str, ...], *, timeout_seconds: int = 12) -> list[NewsItem]:
    items: list[NewsItem] = []
    for url in rss_urls:
        try:
            items.extend(_fetch_rss(url, timeout_seconds=timeout_seconds))
        except Exception as exc:  # Keep the daily job resilient across flaky feeds.
            print(f"WARN failed to fetch feed {url}: {exc}", flush=True)
    return items


def _fetch_rss(url: str, *, timeout_seconds: int) -> list[NewsItem]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "daily-ai-tech-news-zeabur/0.1 (+public RSS digest)",
            "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        xml_bytes = response.read()
    root = ET.fromstring(xml_bytes)
    channel_title = _text(root.find("./channel/title")) or _host_label(url)
    parsed: list[NewsItem] = []
    for entry in root.findall("./channel/item"):
        title = _clean_text(_text(entry.find("title")))
        link = _clean_text(_text(entry.find("link")))
        if not title or not link:
            continue
        summary = _clean_text(_text(entry.find("description")))
        source = _clean_text(_text(entry.find("source"))) or channel_title
        parsed.append(
            NewsItem(
                title=title,
                link=link,
                source=source,
                published_at=_parse_datetime(_text(entry.find("pubDate"))),
                summary=summary,
            )
        )
    return parsed


def filter_recent_items(items: list[NewsItem], *, now: datetime, hours: int = 24) -> list[NewsItem]:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    cutoff = now.astimezone(timezone.utc) - timedelta(hours=hours)
    recent: list[NewsItem] = []
    for item in items:
        if item.published_at is None:
            recent.append(item)
            continue
        published_at = item.published_at
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        if published_at.astimezone(timezone.utc) >= cutoff:
            recent.append(item)
    return recent


def pick_top_items(items: list[NewsItem], *, limit: int = 5) -> list[NewsItem]:
    seen_links: set[str] = set()
    deduped: list[NewsItem] = []
    for item in items:
        normalized_link = item.link.split("?")[0].rstrip("/")
        if normalized_link in seen_links:
            continue
        seen_links.add(normalized_link)
        deduped.append(item)

    return sorted(deduped, key=_score_item, reverse=True)[:limit]


def build_digest_message(items: list[NewsItem], *, today: date) -> str:
    lines = [f"今日 AI / 科技新聞（{today.isoformat()}）", ""]
    if not items:
        lines.extend([
            "今天沒有從公開來源取得足夠可靠的 AI / 科技新聞。",
            "建議稍後再檢查公開 RSS 或新聞來源。",
        ])
        return "\n".join(lines)

    for index, item in enumerate(items, start=1):
        tags = _tags_for(item)
        summary = _summary_for(item)
        lines.extend(
            [
                f"{index}. {item.title}",
                summary,
                f"分類：{' '.join(tags)}",
                f"來源：{item.source} {item.link}",
                "",
            ]
        )

    lines.extend(
        [
            "今日重點：",
            "AI 仍是科技新聞主軸；請特別留意模型能力、晶片供應、企業導入與監管風險之間的連動。",
            "注意：以上摘要依公開來源整理；若來源屬預測、傳聞或未確認消息，請以原文標示與後續官方公告為準。",
        ]
    )
    return _fit_telegram_limit("\n".join(lines))


def _score_item(item: NewsItem) -> tuple[int, float]:
    text = f"{item.title} {item.summary}".lower()
    ai_score = sum(1 for keyword in AI_KEYWORDS if keyword in text)
    tech_score = sum(1 for keyword in TECH_KEYWORDS if keyword in text)
    published_ts = item.published_at.timestamp() if item.published_at else 0.0
    return (ai_score * 100 + tech_score * 10, published_ts)


def _tags_for(item: NewsItem) -> list[str]:
    text = f"{item.title} {item.summary}".lower()
    tags: list[str] = []
    if any(keyword in text for keyword in AI_KEYWORDS):
        tags.append("[AI]")
    if any(keyword in text for keyword in ("nvidia", "gpu", "chip", "semiconductor")):
        tags.append("[晶片]")
    if any(keyword in text for keyword in ("security", "cyber", "breach", "vulnerability")):
        tags.append("[資安]")
    if any(keyword in text for keyword in ("startup", "funding", "venture")):
        tags.append("[新創]")
    if not tags:
        tags.append("[科技]")
    return tags


def _summary_for(item: NewsItem) -> str:
    cleaned = item.summary or "這則新聞可能影響 AI / 科技產業的產品方向、企業採用或競爭格局。"
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > 220:
        cleaned = cleaned[:217].rstrip() + "..."
    return f"重點：{cleaned}\n為什麼重要：它有助於判斷 AI 與科技市場今天的產品、基礎設施或監管走向。"


def _fit_telegram_limit(message: str, *, limit: int = 3900) -> str:
    if len(message) <= limit:
        return message
    return message[: limit - 20].rstrip() + "\n…（已截短）"


def _text(element: ET.Element | None) -> str:
    return "" if element is None or element.text is None else element.text


def _clean_text(value: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", html.unescape(value or ""))
    return re.sub(r"\s+", " ", no_tags).strip()


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _host_label(url: str) -> str:
    match = re.search(r"https?://([^/]+)", url)
    return match.group(1) if match else "Public RSS"
