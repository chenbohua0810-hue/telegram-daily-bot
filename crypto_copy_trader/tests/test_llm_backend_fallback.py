from __future__ import annotations

import pytest

from signals.router import FallbackBackend
from signals.router import LLMBackendError


class _OkBackend:
    def __init__(self, name: str, result: dict | list) -> None:
        self.name = name
        self._result = result
        self.calls = 0

    async def score_one(self, prompt: str, *, max_tokens: int) -> dict:
        self.calls += 1
        return self._result  # type: ignore[return-value]

    async def score_batch(self, prompts: list[str], *, max_tokens: int) -> list[dict]:
        self.calls += 1
        return self._result  # type: ignore[return-value]


class _FailBackend:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls = 0

    async def score_one(self, prompt: str, *, max_tokens: int) -> dict:
        self.calls += 1
        raise LLMBackendError(f"{self.name} failed")

    async def score_batch(self, prompts: list[str], *, max_tokens: int) -> list[dict]:
        self.calls += 1
        raise LLMBackendError(f"{self.name} failed")


# ── score_one fallback chain ──────────────────────────────────────────────────

class TestScoreOneFallback:
    @pytest.mark.asyncio
    async def test_primary_success_no_fallback(self) -> None:
        primary = _OkBackend("primary", {"score": 1})
        secondary = _OkBackend("secondary", {"score": 2})
        fallback = FallbackBackend([primary, secondary])

        result = await fallback.score_one("p", max_tokens=100)

        assert result == {"score": 1}
        assert primary.calls == 1
        assert secondary.calls == 0

    @pytest.mark.asyncio
    async def test_primary_fails_secondary_used(self) -> None:
        primary = _FailBackend("primary")
        secondary = _OkBackend("secondary", {"score": 2})
        fallback = FallbackBackend([primary, secondary])

        result = await fallback.score_one("p", max_tokens=100)

        assert result == {"score": 2}
        assert primary.calls == 1
        assert secondary.calls == 1

    @pytest.mark.asyncio
    async def test_primary_and_secondary_fail_tertiary_used(self) -> None:
        primary = _FailBackend("primary")
        secondary = _FailBackend("secondary")
        tertiary = _OkBackend("claude", {"score": 3})
        fallback = FallbackBackend([primary, secondary, tertiary])

        result = await fallback.score_one("p", max_tokens=100)

        assert result == {"score": 3}
        assert primary.calls == 1
        assert secondary.calls == 1
        assert tertiary.calls == 1

    @pytest.mark.asyncio
    async def test_all_fail_raises_backend_error(self) -> None:
        backends = [_FailBackend("a"), _FailBackend("b"), _FailBackend("c")]
        fallback = FallbackBackend(backends)

        with pytest.raises(LLMBackendError):
            await fallback.score_one("p", max_tokens=100)

    @pytest.mark.asyncio
    async def test_all_fail_all_backends_tried(self) -> None:
        a, b, c = _FailBackend("a"), _FailBackend("b"), _FailBackend("c")
        fallback = FallbackBackend([a, b, c])

        with pytest.raises(LLMBackendError):
            await fallback.score_one("p", max_tokens=100)

        assert a.calls == 1
        assert b.calls == 1
        assert c.calls == 1


# ── score_batch fallback chain ────────────────────────────────────────────────

class TestScoreBatchFallback:
    @pytest.mark.asyncio
    async def test_primary_success_no_fallback(self) -> None:
        primary = _OkBackend("primary", [{"score": 1}, {"score": 2}])
        secondary = _OkBackend("secondary", [{"score": 9}])
        fallback = FallbackBackend([primary, secondary])

        result = await fallback.score_batch(["p"], max_tokens=100)

        assert len(result) == 2
        assert secondary.calls == 0

    @pytest.mark.asyncio
    async def test_primary_fails_secondary_used(self) -> None:
        primary = _FailBackend("primary")
        secondary = _OkBackend("secondary", [{"score": 2}])
        fallback = FallbackBackend([primary, secondary])

        result = await fallback.score_batch(["p"], max_tokens=100)

        assert result == [{"score": 2}]

    @pytest.mark.asyncio
    async def test_all_fail_raises_backend_error(self) -> None:
        fallback = FallbackBackend([_FailBackend("a"), _FailBackend("b")])

        with pytest.raises(LLMBackendError):
            await fallback.score_batch(["p"], max_tokens=100)


# ── name attribute ────────────────────────────────────────────────────────────

class TestFallbackName:
    def test_name_reflects_backends(self) -> None:
        fallback = FallbackBackend([_OkBackend("groq", {}), _OkBackend("nvidia", {})])
        assert "groq" in fallback.name
        assert "nvidia" in fallback.name
