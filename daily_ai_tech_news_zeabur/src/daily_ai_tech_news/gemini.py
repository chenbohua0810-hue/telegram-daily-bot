from __future__ import annotations

from dataclasses import dataclass
import json
import re
import urllib.parse
import urllib.request

from .digest import DigestEntry, NewsItem


class GeminiError(RuntimeError):
    """Raised when Gemini cannot return a valid news digest entry."""


@dataclass(frozen=True)
class GeminiNewsEnricher:
    api_key: str
    model: str = "gemini-2.5-flash"
    timeout_seconds: int = 30
    urlopen: object = urllib.request.urlopen

    def enrich_item(self, item: NewsItem) -> DigestEntry:
        text = self._generate_text(_build_prompt(item))
        try:
            entry_payload = json.loads(_extract_json_object(text))
            return _entry_from_payload(entry_payload)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise GeminiError("Gemini returned an invalid news digest entry") from exc

    def enrich_items(self, items: list[NewsItem]) -> list[DigestEntry]:
        if not items:
            return []
        text = self._generate_text(_build_batch_prompt(items))
        try:
            payload = json.loads(_extract_json_array(text))
            if not isinstance(payload, list) or len(payload) != len(items):
                raise ValueError("Gemini returned the wrong number of digest entries")
            return [_entry_from_payload(entry_payload) for entry_payload in payload]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise GeminiError("Gemini returned an invalid news digest batch") from exc

    def _generate_text(self, prompt: str) -> str:
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0.0,
                "maxOutputTokens": 1400,
                "responseMimeType": "application/json",
            },
        }
        request = urllib.request.Request(
            _endpoint(self.model, self.api_key),
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except Exception as exc:
            raise GeminiError(f"Gemini request failed: {exc}") from exc

        try:
            response_payload = json.loads(raw)
            return response_payload["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise GeminiError("Gemini returned an invalid generateContent response") from exc


def _endpoint(model: str, api_key: str) -> str:
    encoded_model = urllib.parse.quote(model, safe="")
    encoded_key = urllib.parse.quote(api_key, safe="")
    return f"https://generativelanguage.googleapis.com/v1beta/models/{encoded_model}:generateContent?key={encoded_key}"


def _build_prompt(item: NewsItem) -> str:
    summary = item.summary or "（來源未提供摘要）"
    return f"""你是科技新聞編輯。請根據以下公開新聞資料，輸出繁體中文 JSON。

要求：
- title：把原始標題翻成自然、精準的繁體中文；保留公司、產品、模型名稱。
- key_point：寫文章本身的實際重點，只能根據標題與摘要，不要編造。
- key_point 不要寫成泛用分類說明，例如「這則新聞與 AI 相關」或「值得觀察後續影響」。
- 不要輸出來源、連結、分類、Markdown 或額外文字。
- 若摘要不足，只根據標題保守描述已知事實。

輸出格式：
{{"title":"繁體中文標題","key_point":"一到兩句繁體中文實際重點"}}

原始標題：{item.title}
來源：{item.source}
摘要：{summary}
"""


def _build_batch_prompt(items: list[NewsItem]) -> str:
    lines = [
        "你是科技新聞編輯。請根據以下公開 AI 新聞資料，輸出繁體中文 JSON array。",
        "",
        "要求：",
        "- 只回傳 JSON array，不要 Markdown、不要前後說明文字。",
        "- array 長度必須等於輸入新聞數量，順序也必須相同。",
        "- 每個物件只能有 title 與 key_point 兩個欄位。",
        "- title：把原始標題翻成自然、精準的繁體中文；保留公司、產品、模型名稱。",
        "- key_point：寫文章本身的實際重點，只能根據標題與摘要，不要編造。",
        "- key_point 不要寫成泛用分類說明，例如「這則新聞與 AI 相關」或「值得觀察後續影響」。",
        "- 若摘要不足，只根據標題保守描述已知事實。",
        "",
        "輸出格式：",
        '[{"title":"繁體中文標題","key_point":"一到兩句繁體中文實際重點"}]',
        "",
        "新聞：",
    ]
    for index, item in enumerate(items, start=1):
        summary = item.summary or "（來源未提供摘要）"
        lines.extend(
            [
                f"{index}.",
                f"原始標題：{item.title}",
                f"來源：{item.source}",
                f"摘要：{summary}",
                "",
            ]
        )
    return "\n".join(lines)


def _entry_from_payload(entry_payload: object) -> DigestEntry:
    if not isinstance(entry_payload, dict):
        raise ValueError("Digest entry must be an object")
    title = _clean_output(entry_payload["title"], limit=80)
    key_point = _clean_output(entry_payload["key_point"], limit=120)
    if not title or not key_point:
        raise ValueError("Digest entry has empty title or key point")
    return DigestEntry(title=title, key_point=key_point)


def _extract_json_object(value: str) -> str:
    text = _strip_json_fence(value)
    try:
        json.loads(text)
        return text
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fenced:
        return fenced.group(1).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in Gemini response")
    return text[start : end + 1].strip()


def _extract_json_array(value: str) -> str:
    text = _strip_json_fence(value)
    try:
        payload = json.loads(text)
        if isinstance(payload, list):
            return text
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, flags=re.DOTALL)
    if fenced:
        return fenced.group(1).strip()

    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON array found in Gemini response")
    return text[start : end + 1].strip()


def _strip_json_fence(value: str) -> str:
    text = value.strip()
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    return match.group(1).strip() if match else text


def _clean_output(value: str, *, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value)).strip()
    if len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text
