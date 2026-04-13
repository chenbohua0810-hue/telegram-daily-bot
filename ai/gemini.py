from google import genai
from news.rss import NewsItem
from news.throk import TrendingPost

PROMPT_TEMPLATE = '''你是一個繁體中文新聞編輯。請將以下新聞整理成簡潔的日報摘要，使用繁體中文，格式為 Telegram Markdown。

新聞來源：
{news_section}

Threads 熱門話題：
{threads_section}

請輸出：
1. 5 則最重要的新聞（每則一行，含簡短說明）
2. 3 則 Threads 熱門話題

格式範例：
📰 *今日新聞*
• [標題](連結) — 一句話摘要
...

🔥 *Threads 熱門*
• 話題內容
...'''


def _build_prompt(news_items: list, trending: list) -> str:
    news_section = '\n'.join(
        f'- {item.title}: {item.summary} ({item.url})' for item in news_items
    )
    threads_section = (
        '\n'.join(
            f'- {post.text} (互動：{post.engagement})' for post in trending
        )
        or '（無資料）'
    )
    return PROMPT_TEMPLATE.format(
        news_section=news_section,
        threads_section=threads_section,
    )


def _fallback_summary(news_items: list, trending: list) -> str:
    lines = ['📰 *今日新聞*（摘要服務暫時不可用）']
    for item in news_items[:5]:
        lines.append(f'• [{item.title}]({item.url})')
    if trending:
        lines.append('\n🔥 *Threads 熱門*')
        for post in trending[:3]:
            lines.append(f'• {post.text}')
    return '\n'.join(lines)


def summarize_news(news_items: list, trending: list, api_key: str) -> str:
    try:
        client = genai.Client(api_key=api_key)
        prompt = _build_prompt(news_items, trending)
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt,
        )
        return response.text
    except Exception:
        return _fallback_summary(news_items, trending)
