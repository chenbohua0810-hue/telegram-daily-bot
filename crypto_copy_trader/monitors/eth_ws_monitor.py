from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

from models.events import OnChainEvent
from monitors.base import WebSocketChainMonitor
from monitors.eth_monitor import EthMonitor


class EthWebSocketMonitor(WebSocketChainMonitor):
    chain = "eth"

    def __init__(
        self,
        *,
        rest_monitor: EthMonitor,
        ws_url: str,
        heartbeat_timeout_seconds: int,
        reconnect_backoff_cap_seconds: int,
        connect_message_stream: Callable[[], AsyncIterator[Any]] | None = None,
        parse_message: Callable[[Any], list[OnChainEvent]] | None = None,
    ) -> None:
        super().__init__(
            rest_monitor=rest_monitor,
            ws_url=ws_url,
            heartbeat_timeout_seconds=heartbeat_timeout_seconds,
            reconnect_backoff_cap_seconds=reconnect_backoff_cap_seconds,
        )
        self._connect_message_stream_override = connect_message_stream
        self._parse_message_override = parse_message

    def _connect_message_stream(self) -> AsyncIterator[Any]:
        if self._connect_message_stream_override is None:
            raise NotImplementedError("Alchemy websocket connection is not configured")
        return self._connect_message_stream_override()

    async def _parse_message(self, message: Any) -> list[OnChainEvent]:
        if self._parse_message_override is None:
            return []
        return self._parse_message_override(message)
