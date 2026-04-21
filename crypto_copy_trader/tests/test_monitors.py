from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest

from models.events import OnChainEvent
from monitors.base import ChainMonitor
from storage.addresses_repo import AddressesRepo


def build_event(
    *,
    wallet: str = "0xabc123",
    tx_hash: str = "0xtxhash",
    block_number: int = 123,
) -> OnChainEvent:
    return OnChainEvent(
        chain="eth",
        wallet=wallet,
        tx_hash=tx_hash,
        block_time=datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc),
        tx_type="swap_in",
        token_symbol="ETH",
        amount_token=Decimal("1"),
        amount_usd=Decimal("2000"),
        raw={"block_number": block_number},
    )


@dataclass
class StubMonitor(ChainMonitor):
    chain: str = "eth"

    def __init__(self, api_key: str, addresses_repo: AddressesRepo, event_log: object) -> None:
        super().__init__(api_key, addresses_repo, event_log)
        self._fetch_mock = AsyncMock(return_value=[])

    async def fetch_new_transactions(self, address: str, since_block: int | None) -> list[OnChainEvent]:
        return await self._fetch_mock(address, since_block)


@pytest.mark.asyncio
async def test_poll_once_skips_inactive_wallets(tmp_path: pytest.TempPathFactory) -> None:
    db_path = tmp_path / "addresses.db"
    repo = AddressesRepo(str(db_path))
    repo.upsert_wallet(
        score=_wallet(address="0x1", chain="eth", status="active"),
    )
    repo.upsert_wallet(
        score=_wallet(address="0x2", chain="eth", status="active"),
    )
    repo.upsert_wallet(
        score=_wallet(address="0x3", chain="eth", status="retired"),
    )

    monitor = StubMonitor(api_key="key", addresses_repo=repo, event_log=Mock())

    await monitor.poll_once()

    called_addresses = [call.args[0] for call in monitor._fetch_mock.await_args_list]

    assert called_addresses == ["0x1", "0x2"]


@pytest.mark.asyncio
async def test_poll_once_logs_events(tmp_path: pytest.TempPathFactory) -> None:
    db_path = tmp_path / "addresses.db"
    repo = AddressesRepo(str(db_path))
    repo.upsert_wallet(
        score=_wallet(address="0x1", chain="eth", status="active"),
    )
    event_log = Mock()
    monitor = StubMonitor(api_key="key", addresses_repo=repo, event_log=event_log)
    monitor._fetch_mock = AsyncMock(
        return_value=[
            build_event(tx_hash="0x1", block_number=11),
            build_event(tx_hash="0x2", block_number=12),
        ]
    )

    events = await monitor.poll_once()

    assert len(events) == 2
    assert event_log.append.call_count == 2
    assert monitor.last_seen_blocks["0x1"] == 12


def _wallet(*, address: str, chain: str, status: str):
    from models.signals import WalletScore

    return WalletScore(
        address=address,
        chain=chain,
        win_rate=0.7,
        trade_count=50,
        max_drawdown=0.2,
        funds_usd=100000.0,
        recent_win_rate=0.72,
        trust_level="high",
        status=status,
    )
