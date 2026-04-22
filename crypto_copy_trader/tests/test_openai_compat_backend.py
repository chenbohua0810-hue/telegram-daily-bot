from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from signals.backends.openai_compat_backend import OpenAICompatBackend
from signals.llm_backend import LLMBackendError


def _make_response(body: dict | list, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps(body)}}]
    }
    return resp


def _make_backend(
    responses: list[MagicMock],
    supports_json_mode: bool = True,
) -> tuple[OpenAICompatBackend, MagicMock]:
    mock_client = MagicMock()
    mock_post = AsyncMock(side_effect=responses)
    mock_client.post = mock_post
    backend = OpenAICompatBackend(
        client=mock_client,
        base_url="https://api.groq.com/openai/v1",
        model="llama-3.3-70b-versatile",
        api_key="test-key",
        supports_json_mode=supports_json_mode,
    )
    return backend, mock_client


# ── score_one happy path ──────────────────────────────────────────────────────

class TestScoreOneHappyPath:
    @pytest.mark.asyncio
    async def test_200_returns_parsed_dict(self) -> None:
        payload = {"confidence_score": 75, "reasoning": "ok", "recommendation": "execute"}
        backend, _ = _make_backend([_make_response(payload)])

        result = await backend.score_one("prompt", max_tokens=300)

        assert result["confidence_score"] == 75

    @pytest.mark.asyncio
    async def test_markdown_fence_stripped(self) -> None:
        inner = '{"confidence_score": 72, "reasoning": "ok", "recommendation": "execute"}'
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "choices": [{"message": {"content": f"```json\n{inner}\n```"}}]
        }
        backend, _ = _make_backend([resp])

        result = await backend.score_one("prompt", max_tokens=300)

        assert result["confidence_score"] == 72

    @pytest.mark.asyncio
    async def test_json_mode_sent_when_supported(self) -> None:
        payload = {"confidence_score": 70, "reasoning": "ok", "recommendation": "skip"}
        backend, mock_client = _make_backend([_make_response(payload)], supports_json_mode=True)

        await backend.score_one("prompt", max_tokens=100)

        call_kwargs = mock_client.post.call_args.kwargs
        body = call_kwargs.get("json", {})
        assert body.get("response_format") == {"type": "json_object"}

    @pytest.mark.asyncio
    async def test_json_mode_omitted_when_not_supported(self) -> None:
        payload = {"confidence_score": 70, "reasoning": "ok", "recommendation": "skip"}
        backend, mock_client = _make_backend([_make_response(payload)], supports_json_mode=False)

        await backend.score_one("prompt", max_tokens=100)

        call_kwargs = mock_client.post.call_args.kwargs
        body = call_kwargs.get("json", {})
        assert "response_format" not in body

    @pytest.mark.asyncio
    async def test_max_tokens_forwarded(self) -> None:
        payload = {"confidence_score": 70, "reasoning": "ok", "recommendation": "skip"}
        backend, mock_client = _make_backend([_make_response(payload)])

        await backend.score_one("prompt", max_tokens=42)

        body = mock_client.post.call_args.kwargs.get("json", {})
        assert body["max_tokens"] == 42


# ── retry behaviour ───────────────────────────────────────────────────────────

class TestRetry:
    @pytest.mark.asyncio
    async def test_429_retries_once_then_succeeds(self) -> None:
        payload = {"confidence_score": 65, "reasoning": "ok", "recommendation": "execute"}
        rate_limit = MagicMock()
        rate_limit.status_code = 429
        success = _make_response(payload)

        backend, mock_client = _make_backend([rate_limit, success])

        result = await backend.score_one("prompt", max_tokens=300)

        assert result["confidence_score"] == 65
        assert mock_client.post.await_count == 2

    @pytest.mark.asyncio
    async def test_500_retries_once_then_succeeds(self) -> None:
        payload = {"confidence_score": 60, "reasoning": "ok", "recommendation": "skip"}
        server_err = MagicMock()
        server_err.status_code = 500
        success = _make_response(payload)

        backend, mock_client = _make_backend([server_err, success])

        result = await backend.score_one("prompt", max_tokens=300)

        assert result["confidence_score"] == 60
        assert mock_client.post.await_count == 2

    @pytest.mark.asyncio
    async def test_two_429s_raise_backend_error(self) -> None:
        rate_limit = MagicMock()
        rate_limit.status_code = 429
        backend, _ = _make_backend([rate_limit, rate_limit])

        with pytest.raises(LLMBackendError):
            await backend.score_one("prompt", max_tokens=300)

    @pytest.mark.asyncio
    async def test_two_500s_raise_backend_error(self) -> None:
        server_err = MagicMock()
        server_err.status_code = 500
        backend, _ = _make_backend([server_err, server_err])

        with pytest.raises(LLMBackendError):
            await backend.score_one("prompt", max_tokens=300)

    @pytest.mark.asyncio
    async def test_network_exception_raises_backend_error(self) -> None:
        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=RuntimeError("connection refused"))
        backend = OpenAICompatBackend(
            client=mock_client,
            base_url="http://x",
            model="m",
            api_key="k",
        )

        with pytest.raises(LLMBackendError):
            await backend.score_one("prompt", max_tokens=300)


# ── name attribute ────────────────────────────────────────────────────────────

class TestBackendName:
    def test_name_reflects_constructor(self) -> None:
        mock_client = MagicMock()
        backend = OpenAICompatBackend(
            client=mock_client, base_url="http://x", model="m", api_key="k", name="groq"
        )
        assert backend.name == "groq"

    def test_default_name_is_openai_compat(self) -> None:
        mock_client = MagicMock()
        backend = OpenAICompatBackend(
            client=mock_client, base_url="http://x", model="m", api_key="k"
        )
        assert backend.name == "openai_compat"
