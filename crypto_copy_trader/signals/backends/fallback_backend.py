from __future__ import annotations

from typing import TYPE_CHECKING

from signals.llm_backend import LLMBackendError

if TYPE_CHECKING:
    from signals.llm_backend import LLMBackend


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
