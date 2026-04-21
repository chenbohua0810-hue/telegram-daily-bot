from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Literal

import httpx

from models.events import OnChainEvent
from storage.addresses_repo import AddressesRepo
from storage.event_log import EventLog


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

            for event in wallet_events:
                self.event_log.append(event)

            if wallet_events:
                self.last_seen_blocks[wallet.address] = self._max_block_marker(wallet_events)

            events.extend(wallet_events)

        return events

    @property
    def client(self) -> httpx.AsyncClient:
        if self._active_client is None:
            raise RuntimeError("HTTP client is not initialized")
        return self._active_client

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
