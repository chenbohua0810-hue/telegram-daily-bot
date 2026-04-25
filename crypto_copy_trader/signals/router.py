from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

from models import OnChainEvent, WalletScore


# ---------------------------------------------------------------------------
# llm_backend (protocol + helpers)
# ---------------------------------------------------------------------------


class LLMBackendError(RuntimeError):
    pass


@runtime_checkable
class LLMBackend(Protocol):
    name: str

    async def score_one(self, prompt: str, *, max_tokens: int) -> dict: ...
    async def score_batch(self, prompts: list[str], *, max_tokens: int) -> list[dict]: ...


def strip_markdown_fence(value: str) -> str:
    text = value.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return text


# ---------------------------------------------------------------------------
# anthropic_backend
# ---------------------------------------------------------------------------


class AnthropicBackend:
    name = "claude"

    def __init__(self, client: Any, model: str, system_prompt: str = "") -> None:
        self._client = client
        self._model = model
        self._system_prompt = system_prompt

    async def score_one(self, prompt: str, *, max_tokens: int) -> dict:
        last_error: Exception | None = None
        for _ in range(2):
            try:
                kwargs: dict = dict(
                    model=self._model,
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": prompt}],
                )
                if self._system_prompt:
                    kwargs["system"] = self._system_prompt
                response = await self._client.messages.create(**kwargs)
                text = strip_markdown_fence(response.content[0].text)
                return json.loads(text)
            except Exception as exc:
                last_error = exc
        raise LLMBackendError("AnthropicBackend.score_one failed") from last_error

    async def score_batch(self, prompts: list[str], *, max_tokens: int) -> list[dict]:
        if not prompts:
            return []
        combined = prompts[0]
        last_error: Exception | None = None
        for _ in range(2):
            try:
                kwargs: dict = dict(
                    model=self._model,
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": combined}],
                )
                if self._system_prompt:
                    kwargs["system"] = self._system_prompt
                response = await self._client.messages.create(**kwargs)
                text = strip_markdown_fence(response.content[0].text)
                result = json.loads(text)
                if not isinstance(result, list):
                    raise ValueError(f"Expected JSON array, got {type(result)}")
                return result
            except Exception as exc:
                last_error = exc
        raise LLMBackendError("AnthropicBackend.score_batch failed") from last_error


# ---------------------------------------------------------------------------
# openai_compat_backend
# ---------------------------------------------------------------------------

_RETRY_STATUSES = {429, 500, 502, 503, 504}
_BACKOFF_SECONDS = 0.5


class OpenAICompatBackend:
    def __init__(
        self,
        client: Any,
        base_url: str,
        model: str,
        api_key: str,
        name: str = "openai_compat",
        supports_json_mode: bool = True,
    ) -> None:
        self.name = name
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._supports_json_mode = supports_json_mode

    async def score_one(self, prompt: str, *, max_tokens: int) -> dict:
        result = await self._call_with_retry(
            [{"role": "user", "content": prompt}], max_tokens=max_tokens
        )
        if not isinstance(result, dict):
            raise LLMBackendError(f"score_one expected dict, got {type(result)}")
        return result

    async def score_batch(self, prompts: list[str], *, max_tokens: int) -> list[dict]:
        if not prompts:
            return []
        result = await self._call_with_retry(
            [{"role": "user", "content": prompts[0]}], max_tokens=max_tokens
        )
        if not isinstance(result, list):
            raise LLMBackendError(f"score_batch expected list, got {type(result)}")
        return result

    async def _call_with_retry(self, messages: list[dict], *, max_tokens: int) -> dict | list:
        last_status: int | None = None
        for attempt in range(2):
            try:
                return await self._post(messages, max_tokens=max_tokens)
            except _RetryableHTTPError as exc:
                last_status = exc.status_code
                if attempt == 0:
                    await asyncio.sleep(_BACKOFF_SECONDS)
            except Exception as exc:
                raise LLMBackendError("OpenAICompatBackend request failed") from exc
        raise LLMBackendError(f"OpenAICompatBackend HTTP {last_status} after retry")

    async def _post(self, messages: list[dict], *, max_tokens: int) -> dict | list:
        body: dict = {
            "model": self._model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if self._supports_json_mode:
            body["response_format"] = {"type": "json_object"}

        response = await self._client.post(
            f"{self._base_url}/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {self._api_key}"},
        )

        if response.status_code in _RETRY_STATUSES:
            raise _RetryableHTTPError(response.status_code)

        if response.status_code != 200:
            raise LLMBackendError(f"OpenAICompatBackend HTTP {response.status_code}")

        data = response.json()
        text = strip_markdown_fence(data["choices"][0]["message"]["content"])
        return json.loads(text)


class _RetryableHTTPError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


# ---------------------------------------------------------------------------
# fallback_backend
# ---------------------------------------------------------------------------


class FallbackBackend:
    def __init__(self, backends: list["LLMBackend"]) -> None:
        if not backends:
            raise ValueError("FallbackBackend requires at least one backend")
        self._backends = backends
        self.name = ">".join(b.name for b in backends)
        self._total_calls = 0
        self._fallback_calls = 0

    @property
    def fallback_rate(self) -> float:
        if self._total_calls == 0:
            return 0.0
        return self._fallback_calls / self._total_calls

    async def score_one(self, prompt: str, *, max_tokens: int) -> dict:
        self._total_calls += 1
        last_error: LLMBackendError | None = None
        used_fallback = False
        for index, backend in enumerate(self._backends):
            try:
                if index > 0:
                    used_fallback = True
                result = await backend.score_one(prompt, max_tokens=max_tokens)
                if used_fallback:
                    self._fallback_calls += 1
                return result
            except LLMBackendError as exc:
                last_error = exc
        raise LLMBackendError(f"All backends failed: {self.name}") from last_error

    async def score_batch(self, prompts: list[str], *, max_tokens: int) -> list[dict]:
        self._total_calls += 1
        last_error: LLMBackendError | None = None
        used_fallback = False
        for index, backend in enumerate(self._backends):
            try:
                if index > 0:
                    used_fallback = True
                result = await backend.score_batch(prompts, max_tokens=max_tokens)
                if used_fallback:
                    self._fallback_calls += 1
                return result
            except LLMBackendError as exc:
                last_error = exc
        raise LLMBackendError(f"All backends failed: {self.name}") from last_error


# ---------------------------------------------------------------------------
# priority_router
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PriorityDecision:
    level: Literal["P0", "P1", "P2", "P3"]
    reason: str


def assign_priority(
    event: OnChainEvent,
    wallet: WalletScore,
    *,
    known_tokens: set[str],
    quant_passed: bool,
    high_value_usd: float,
    p1_min_usd: float,
    p1_min_win_rate: float,
) -> PriorityDecision:
    if not quant_passed:
        return PriorityDecision(level="P3", reason="quant_filter_failed")

    amount = float(event.amount_usd)

    if amount >= high_value_usd:
        return PriorityDecision(level="P0", reason="high_value_usd")

    if event.token_symbol not in known_tokens:
        return PriorityDecision(level="P0", reason="unknown_token")

    if (
        wallet.trust_level == "high"
        and wallet.recent_win_rate >= p1_min_win_rate
        and amount >= p1_min_usd
    ):
        return PriorityDecision(level="P1", reason="high_trust_direct_copy")

    return PriorityDecision(level="P2", reason="batch_scorer")
