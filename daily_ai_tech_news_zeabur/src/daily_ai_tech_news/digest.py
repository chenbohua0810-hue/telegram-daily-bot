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


@dataclass(frozen=True)
class DigestEntry:
    title: str
    key_point: str


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


def enrich_news_items(items: list[NewsItem], *, enricher: object | None = None) -> list[DigestEntry]:
    entries: list[DigestEntry] = []
    for item in items:
        if enricher is not None:
            try:
                entries.append(enricher.enrich_item(item))
                continue
            except Exception as exc:
                print(f"WARN failed to enrich news title with model: {exc}", flush=True)
        entries.append(_fallback_entry_for(item))
    return entries


def build_digest_message(entries: list[DigestEntry], *, today: date) -> str:
    lines = [f"今日 AI / 科技新聞重點（{today.isoformat()}）", ""]
    if not entries:
        lines.extend([
            "今天沒有從公開來源取得足夠可靠的 AI / 科技新聞。",
            "建議稍後再檢查公開 RSS 或新聞來源。",
        ])
        return "\n".join(lines)

    for index, entry in enumerate(entries, start=1):
        lines.extend(
            [
                f"{index}. 標題：{entry.title}",
                f"重點：{entry.key_point}",
                "",
            ]
        )

    lines.extend(
        [
            "今日重點：",
            "AI 仍是科技新聞主軸；請留意模型能力、算力供應、企業導入與監管風險的連動。",
            "注意：本訊息依公開來源整理；未確認消息不視為事實，請以原文與官方公告為準。",
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


def _fallback_entry_for(item: NewsItem) -> DigestEntry:
    return DigestEntry(title=item.title, key_point=_article_key_point_for(item))


def _article_key_point_for(item: NewsItem) -> str:
    cleaned = re.sub(r"\s+", " ", item.summary or "").strip()
    if cleaned:
        if len(cleaned) > 90:
            cleaned = cleaned[:87].rstrip() + "…"
        return cleaned
    return "公開來源沒有提供足夠摘要；請以標題判斷此新聞與今日科技動態的關聯。"


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
