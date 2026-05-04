from __future__ import annotations

import json
import urllib.parse
import urllib.request


class TelegramError(RuntimeError):
    """Raised when Telegram rejects a sendMessage request."""


def send_telegram_message(*, bot_token: str, chat_id: str, text: str, timeout_seconds: int = 20) -> None:
    endpoint = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": "false",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        body = response.read().decode("utf-8")
    parsed = json.loads(body)
    if not parsed.get("ok"):
        raise TelegramError("Telegram sendMessage returned ok=false")
