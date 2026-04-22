from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from signals.backends.anthropic_backend import AnthropicBackend
from signals.llm_backend import LLMBackendError, strip_markdown_fence


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_client(*texts: str) -> SimpleNamespace:
    async def create(**kwargs):
        return SimpleNamespace(content=[SimpleNamespace(text=responses.pop(0))])

    responses = list(texts)
    return SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(side_effect=create)))


# ── strip_markdown_fence ──────────────────────────────────────────────────────

class TestStripMarkdownFence:
    def test_plain_json_unchanged(self) -> None:
        text = '{"a": 1}'
        assert strip_markdown_fence(text) == text

    def test_json_fence_stripped(self) -> None:
        text = "```json\n{\"a\": 1}\n```"
        assert strip_markdown_fence(text) == '{"a": 1}'

    def test_bare_fence_stripped(self) -> None:
        text = "```\n{\"a\": 1}\n```"
        assert strip_markdown_fence(text) == '{"a": 1}'

    def test_leading_trailing_whitespace_stripped(self) -> None:
        assert strip_markdown_fence("  hello  ") == "hello"


# ── AnthropicBackend.score_one ────────────────────────────────────────────────

class TestScoreOne:
    @pytest.mark.asyncio
    async def test_happy_path_returns_parsed_dict(self) -> None:
        client = _make_client('{"confidence_score": 80, "reasoning": "good", "recommendation": "execute"}')
        backend = AnthropicBackend(client=client, model="claude-test")

        result = await backend.score_one("prompt", max_tokens=300)

        assert result["confidence_score"] == 80
        assert result["recommendation"] == "execute"

    @pytest.mark.asyncio
    async def test_system_prompt_forwarded_when_set(self) -> None:
        client = _make_client('{"confidence_score": 70, "reasoning": "ok", "recommendation": "skip"}')
        backend = AnthropicBackend(client=client, model="claude-test", system_prompt="be concise")

        await backend.score_one("prompt", max_tokens=100)

        call_kwargs = client.messages.create.call_args.kwargs
        assert call_kwargs.get("system") == "be concise"

    @pytest.mark.asyncio
    async def test_no_system_param_when_empty(self) -> None:
        client = _make_client('{"confidence_score": 70, "reasoning": "ok", "recommendation": "skip"}')
        backend = AnthropicBackend(client=client, model="claude-test")

        await backend.score_one("prompt", max_tokens=100)

        call_kwargs = client.messages.create.call_args.kwargs
        assert "system" not in call_kwargs

    @pytest.mark.asyncio
    async def test_max_tokens_forwarded(self) -> None:
        client = _make_client('{"confidence_score": 70, "reasoning": "ok", "recommendation": "skip"}')
        backend = AnthropicBackend(client=client, model="claude-test")

        await backend.score_one("prompt", max_tokens=42)

        call_kwargs = client.messages.create.call_args.kwargs
        assert call_kwargs["max_tokens"] == 42

    @pytest.mark.asyncio
    async def test_markdown_fence_stripped(self) -> None:
        client = _make_client('```json\n{"confidence_score": 72, "reasoning": "ok", "recommendation": "execute"}\n```')
        backend = AnthropicBackend(client=client, model="claude-test")

        result = await backend.score_one("prompt", max_tokens=300)

        assert result["confidence_score"] == 72

    @pytest.mark.asyncio
    async def test_invalid_json_retries_once(self) -> None:
        client = _make_client(
            "not json",
            '{"confidence_score": 65, "reasoning": "retry ok", "recommendation": "execute"}',
        )
        backend = AnthropicBackend(client=client, model="claude-test")

        result = await backend.score_one("prompt", max_tokens=300)

        assert result["confidence_score"] == 65
        assert client.messages.create.await_count == 2

    @pytest.mark.asyncio
    async def test_all_attempts_fail_raises_backend_error(self) -> None:
        client = _make_client("not json", "still not json")
        backend = AnthropicBackend(client=client, model="claude-test")

        with pytest.raises(LLMBackendError):
            await backend.score_one("prompt", max_tokens=300)

    @pytest.mark.asyncio
    async def test_api_exception_raises_backend_error(self) -> None:
        async def failing_create(**_):
            raise RuntimeError("network error")

        client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(side_effect=failing_create)))
        backend = AnthropicBackend(client=client, model="claude-test")

        with pytest.raises(LLMBackendError):
            await backend.score_one("prompt", max_tokens=300)


# ── AnthropicBackend.score_batch ──────────────────────────────────────────────

class TestScoreBatch:
    @pytest.mark.asyncio
    async def test_single_combined_prompt_returns_array(self) -> None:
        array_json = (
            '[{"index": 1, "confidence_score": 80, "reasoning": "a", "recommendation": "execute"},'
            ' {"index": 2, "confidence_score": 40, "reasoning": "b", "recommendation": "skip"}]'
        )
        client = _make_client(array_json)
        backend = AnthropicBackend(client=client, model="claude-test")

        results = await backend.score_batch(["combined prompt"], max_tokens=500)

        assert len(results) == 2
        assert results[0]["confidence_score"] == 80
        assert results[1]["confidence_score"] == 40

    @pytest.mark.asyncio
    async def test_batch_failure_raises_backend_error(self) -> None:
        client = _make_client("not json", "not json")
        backend = AnthropicBackend(client=client, model="claude-test")

        with pytest.raises(LLMBackendError):
            await backend.score_batch(["prompt"], max_tokens=300)


# ── name attribute ────────────────────────────────────────────────────────────

class TestBackendName:
    def test_name_is_claude(self) -> None:
        backend = AnthropicBackend(client=None, model="x")
        assert backend.name == "claude"
