from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Iterable
from typing import Any, Literal

import httpx

from models.events import OnChainEvent
from storage.addresses_repo import AddressesRepo
from storage.event_log import EventLog


logger = logging.getLogger(__name__)


class ChainMonitor(ABC):
    chain: Literal["eth", "sol", "bsc"]

    def __init__(
        self,
        api_key: str,
        addresses_repo: AddressesRepo,
        event_log: EventLog,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.addresses_repo = addresses_repo
        self.event_log = event_log
        self._client = client
        self._active_client: httpx.AsyncClient | None = client
        self.last_seen_blocks: dict[str, int] = {}

    @abstractmethod
    async def fetch_new_transactions(
        self,
        address: str,
        since_block: int | None,
    ) -> list[OnChainEvent]: ...

    async def stream(self) -> AsyncIterator[OnChainEvent]:
        while True:
            for event in await self.poll_once():
                yield event
            await asyncio.sleep(1)

    async def poll_once(self) -> list[OnChainEvent]:
        if self._client is None:
            async with httpx.AsyncClient(timeout=30) as client:
                self._active_client = client
                return await self._poll_with_client()

        self._active_client = self._client
        return await self._poll_with_client()

    async def _poll_with_client(self) -> list[OnChainEvent]:
        events: list[OnChainEvent] = []

        for wallet in self.addresses_repo.list_active(chain=self.chain):
            wallet_events = await self.fetch_new_transactions(
                wallet.address,
                self.last_seen_blocks.get(wallet.address),
            )
            recorded_events = self._record_events(wallet_events)
            if recorded_events:
                self.last_seen_blocks[wallet.address] = self._max_block_marker(recorded_events)
            events.extend(recorded_events)

        return events

    @property
    def client(self) -> httpx.AsyncClient:
        if self._active_client is None:
            raise RuntimeError("HTTP client is not initialized")
        return self._active_client

    def _record_events(self, events: Iterable[OnChainEvent]) -> list[OnChainEvent]:
        recorded_events = list(events)
        for event in recorded_events:
            self.event_log.append(event)

        return recorded_events

    def _max_block_marker(self, events: Iterable[OnChainEvent]) -> int:
        markers = [self._extract_block_marker(event) for event in events]
        return max(marker for marker in markers if marker is not None)

    @staticmethod
    def _extract_block_marker(event: OnChainEvent) -> int | None:
        for key in ("block_number", "blockNumber", "slot"):
            value = event.raw.get(key)
            if value is None:
                continue
            return int(value)
        return None


class WebSocketChainMonitor(ChainMonitor):
    def __init__(
        self,
        rest_monitor: ChainMonitor,
        *,
        ws_url: str,
        heartbeat_timeout_seconds: int,
        reconnect_backoff_cap_seconds: int,
    ) -> None:
        super().__init__(
            api_key=rest_monitor.api_key,
            addresses_repo=rest_monitor.addresses_repo,
            event_log=rest_monitor.event_log,
            client=getattr(rest_monitor, "_client", None),
        )
        self._rest_monitor = rest_monitor
        self._ws_url = ws_url
        self._heartbeat_timeout_seconds = heartbeat_timeout_seconds
        self._reconnect_backoff_cap_seconds = reconnect_backoff_cap_seconds
        self.last_seen_blocks = rest_monitor.last_seen_blocks
        self.ws_reconnect_count = 0

    async def fetch_new_transactions(
        self,
        address: str,
        since_block: int | None,
    ) -> list[OnChainEvent]:
        return await self._rest_monitor.fetch_new_transactions(address, since_block)

    async def poll_once(self) -> list[OnChainEvent]:
        return await self._rest_monitor.poll_once()

    async def stream(self) -> AsyncIterator[OnChainEvent]:
        backoff_seconds = 1
        has_connected_before = False

        while True:
            try:
                if has_connected_before:
                    self.ws_reconnect_count += 1
                    logger.warning("%s websocket reconnect attempt %s", self.chain, self.ws_reconnect_count)

                for event in await self._recover_gap_events():
                    yield event

                if not self._ws_url:
                    await asyncio.sleep(1)
                    has_connected_before = True
                    continue

                message_stream = self._connect_message_stream()
                async for event in self._consume_message_stream(message_stream):
                    yield event

                raise ConnectionError(f"{self.chain} websocket stream closed")
            except asyncio.CancelledError:
                raise
            except Exception:
                has_connected_before = True
                await asyncio.sleep(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2, self._reconnect_backoff_cap_seconds)
            else:
                backoff_seconds = 1

    async def _recover_gap_events(self) -> list[OnChainEvent]:
        events: list[OnChainEvent] = []
        for wallet in self.addresses_repo.list_active(chain=self.chain):
            wallet_events = await self._rest_monitor.fetch_new_transactions(
                wallet.address,
                self.last_seen_blocks.get(wallet.address),
            )
            recorded_events = self._record_events(wallet_events)
            if recorded_events:
                self.last_seen_blocks[wallet.address] = self._max_block_marker(recorded_events)
            events.extend(recorded_events)
        return events

    async def _consume_message_stream(self, message_stream: AsyncIterator[Any]) -> AsyncIterator[OnChainEvent]:
        iterator = message_stream.__aiter__()
        while True:
            try:
                message = await asyncio.wait_for(
                    iterator.__anext__(),
                    timeout=self._heartbeat_timeout_seconds,
                )
            except StopAsyncIteration as exc:
                raise ConnectionError(f"{self.chain} websocket stream closed") from exc
            except TimeoutError as exc:
                raise TimeoutError(f"{self.chain} websocket heartbeat timeout") from exc

            for event in self._record_events(await self._parse_message(message)):
                yield event

    @abstractmethod
    def _connect_message_stream(self) -> AsyncIterator[Any]: ...

    @abstractmethod
    async def _parse_message(self, message: Any) -> list[OnChainEvent]: ...
