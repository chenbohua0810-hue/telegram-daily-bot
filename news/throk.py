from dataclasses import dataclass

import httpx

THROK_API_BASE = 'https://api.throk.ai/v1'


@dataclass
class TrendingPost:
    text: str
    engagement: int
    url: str


async def fetch_trending_threads(api_key: str, limit: int = 3) -> list[TrendingPost]:
    try:
        headers = {'Authorization': f'Bearer {api_key}'}
        params = {'limit': limit}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f'{THROK_API_BASE}/trending',
                headers=headers,
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

        return [
            TrendingPost(
                text=item['text'],
                engagement=item.get('engagement', 0),
                url=item.get('url', ''),
            )
            for item in data.get('data', [])[:limit]
        ]
    except Exception:
        return []
