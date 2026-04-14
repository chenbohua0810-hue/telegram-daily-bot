import logging

from google import genai

from news.rss import NewsItem

logger = logging.getLogger(__name__)

PROMPT_TEMPLATE = '''你是一個繁體中文新聞編輯。請將以下新聞整理成簡潔的日報摘要，使用繁體中文，格式為 Telegram Markdown。

新聞來源：
{news_section}

請輸出：
5 則最重要的新聞（每則一行，含簡短說明）

格式範例：
📰 *今日新聞*
• [標題](連結) — 一句話摘要
...'''

_client_cache: dict[str, genai.Client] = {}


def _get_client(api_key: str) -> genai.Client:
    if api_key not in _client_cache:
        _client_cache[api_key] = genai.Client(api_key=api_key)
    return _client_cache[api_key]


def _build_prompt(news_items: list[NewsItem]) -> str:
    news_section = '\n'.join(
        f'- {item.title}: {item.summary} ({item.url})' for item in news_items
    )
    return PROMPT_TEMPLATE.format(news_section=news_section)


def _fallback_summary(news_items: list[NewsItem]) -> str:
    lines = ['📰 *今日新聞*（摘要服務暫時不可用）']
    for item in news_items[:5]:
        lines.append(f'• [{item.title}]({item.url})')
    return '\n'.join(lines)


def summarize_news(news_items: list[NewsItem], api_key: str) -> str:
    try:
        client = _get_client(api_key)
        prompt = _build_prompt(news_items)
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt,
        )
        return response.text
    except Exception as exc:
        logger.warning('Gemini summarization failed, using fallback: %s', exc)
        return _fallback_summary(news_items)
