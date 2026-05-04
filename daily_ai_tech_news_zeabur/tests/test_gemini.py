import json

import pytest

from daily_ai_tech_news.digest import NewsItem
from daily_ai_tech_news.gemini import GeminiNewsEnricher, GeminiError


class FakeResponse:
    def __init__(self, payload: dict, status: int = 200):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_gemini_news_enricher_requests_traditional_chinese_title_and_article_key_point():
    # Arrange
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": '{"title":"OpenAI 發表新的代理模型","key_point":"新模型主打工具使用與低延遲，瞄準企業工作流程導入。"}'
                                }
                            ]
                        }
                    }
                ]
            }
        )

    enricher = GeminiNewsEnricher(api_key="test-key", model="gemini-2.5-flash-lite", urlopen=fake_urlopen)
    item = NewsItem(
        title="OpenAI releases new agent model",
        link="https://example.com/ai",
        source="AIWire",
        published_at=None,
        summary="A new agent model focuses on tool use and lower latency for business workflows.",
    )

    # Act
    entry = enricher.enrich_item(item)

    # Assert
    assert entry.title == "OpenAI 發表新的代理模型"
    assert entry.key_point == "新模型主打工具使用與低延遲，瞄準企業工作流程導入。"
    assert "gemini-2.5-flash-lite:generateContent" in captured["url"]
    prompt = captured["body"]["contents"][0]["parts"][0]["text"]
    assert "繁體中文" in prompt
    assert "文章本身的實際重點" in prompt
    assert "不要寫成泛用分類說明" in prompt
    assert "OpenAI releases new agent model" in prompt


def test_gemini_news_enricher_rejects_invalid_model_response():
    # Arrange
    def fake_urlopen(request, timeout):
        return FakeResponse({"candidates": [{"content": {"parts": [{"text": "not json"}]}}]})

    enricher = GeminiNewsEnricher(api_key="test-key", model="gemini-2.5-flash-lite", urlopen=fake_urlopen)
    item = NewsItem(title="Title", link="https://example.com", source="Source", published_at=None, summary="Summary")

    # Act / Assert
    with pytest.raises(GeminiError):
        enricher.enrich_item(item)
