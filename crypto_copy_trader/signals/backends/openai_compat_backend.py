from __future__ import annotations

import asyncio
import json
from typing import Any

from signals.llm_backend import LLMBackendError, strip_markdown_fence

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
