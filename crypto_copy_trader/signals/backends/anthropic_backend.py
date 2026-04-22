from __future__ import annotations

import json
from typing import Any

from signals.llm_backend import LLMBackendError, strip_markdown_fence


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
        """Send a single combined prompt and parse the JSON-array response."""
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
