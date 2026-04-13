from google import genai
from news.rss import NewsItem

PROMPT_TEMPLATE = '''你是一個繁體中文新聞編輯。請將以下新聞整理成簡潔的日報摘要，使用繁體中文，格式為 Telegram Markdown。

新聞來源：
{news_section}

請輸出：
5 則最重要的新聞（每則一行，含簡短說明）

格式範例：
📰 *今日新聞*
• [標題](連結) — 一句話摘要
...'''


def _build_prompt(news_items: list) -> str:
    news_section = '\n'.join(
        f'- {item.title}: {item.summary} ({item.url})' for item in news_items
    )
    return PROMPT_TEMPLATE.format(news_section=news_section)


def _fallback_summary(news_items: list) -> str:
    lines = ['📰 *今日新聞*（摘要服務暫時不可用）']
    for item in news_items[:5]:
        lines.append(f'• [{item.title}]({item.url})')
    return '\n'.join(lines)


def summarize_news(news_items: list, api_key: str) -> str:
    try:
        client = genai.Client(api_key=api_key)
        prompt = _build_prompt(news_items)
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt,
        )
        return response.text
    except Exception:
        return _fallback_summary(news_items)
