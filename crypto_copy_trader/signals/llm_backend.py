from __future__ import annotations

from typing import Protocol, runtime_checkable


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
