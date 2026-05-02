from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from models import OnChainEvent
from models import WalletScore
from monitors import EthWebSocketMonitor
from storage import AddressesRepo
from storage import EventLog


class _ConnectionDropped(RuntimeError):
    pass


class _ConnectFactory:
    def __init__(self, sequences: list[list[OnChainEvent] | Exception]) -> None:
        self._sequences = list(sequences)

    def __call__(self):
        sequence = self._sequences.pop(0)

        async def iterator():
            if isinstance(sequence, Exception):
                raise sequence
                yield  # pragma: no cover
            for item in sequence:
                yield item

        return iterator()


def build_event(*, tx_hash: str, block_number: int) -> OnChainEvent:
    return OnChainEvent(
        chain="eth",
        wallet="0xabc123",
        tx_hash=tx_hash,
        block_time=datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc),
        tx_type="swap_in",
        token_symbol="ETH",
        amount_token=Decimal("1"),
        amount_usd=Decimal("2000"),
        raw={"block_number": block_number},
        token_address="",
    )


def build_wallet() -> WalletScore:
    return WalletScore(
        address="0xabc123",
        chain="eth",
        win_rate=0.7,
        trade_count=50,
        max_drawdown=0.2,
        funds_usd=100000.0,
        recent_win_rate=0.72,
        trust_level="high",
        status="active",
    )


def build_rest_monitor(tmp_path, fetch_new_transactions: AsyncMock) -> SimpleNamespace:
    addresses_repo = AddressesRepo(str(tmp_path / "addresses.db"))
    addresses_repo.upsert_wallet(build_wallet())
    event_log = EventLog(str(tmp_path / "events.jsonl"))
    return SimpleNamespace(
        api_key="key",
        addresses_repo=addresses_repo,
        event_log=event_log,
        _client=None,
        last_seen_blocks={},
        chain="eth",
        fetch_new_transactions=fetch_new_transactions,
        poll_once=AsyncMock(return_value=[]),
    )


async def collect_events(stream, count: int) -> list[OnChainEvent]:
    events: list[OnChainEvent] = []
    async for event in stream:
        events.append(event)
        if len(events) >= count:
            break
    return events


@pytest.mark.asyncio
async def test_ws_disconnect_triggers_reconnect_with_backoff(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    sleep_mock = AsyncMock(return_value=None)
    monkeypatch.setattr("monitors.asyncio.sleep", sleep_mock)

    rest_monitor = build_rest_monitor(tmp_path, AsyncMock(return_value=[]))
    connect_factory = _ConnectFactory([
        _ConnectionDropped("first"),
        _ConnectionDropped("second"),
        [build_event(tx_hash="tx-success", block_number=101)],
    ])
    monitor = EthWebSocketMonitor(
        rest_monitor=rest_monitor,
        ws_url="wss://eth.example",
        heartbeat_timeout_seconds=1,
        reconnect_backoff_cap_seconds=60,
        connect_message_stream=connect_factory,
        parse_message=lambda message: [message],
    )

    events = await collect_events(monitor.stream(), count=1)

    assert [event.tx_hash for event in events] == ["tx-success"]
    assert sleep_mock.await_args_list[0].args == (1,)
    assert sleep_mock.await_args_list[1].args == (2,)
    assert monitor.ws_reconnect_count == 2


@pytest.mark.asyncio
async def test_gap_backfill_runs_after_every_reconnect(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("monitors.asyncio.sleep", AsyncMock(return_value=None))

    backfill_event = build_event(tx_hash="tx-backfill", block_number=100)
    realtime_event = build_event(tx_hash="tx-live", block_number=101)
    rest_monitor = build_rest_monitor(
        tmp_path,
        AsyncMock(side_effect=[[backfill_event], [realtime_event]]),
    )
    connect_factory = _ConnectFactory([
        _ConnectionDropped("first"),
        [build_event(tx_hash="tx-stream", block_number=102)],
    ])
    monitor = EthWebSocketMonitor(
        rest_monitor=rest_monitor,
        ws_url="wss://eth.example",
        heartbeat_timeout_seconds=1,
        reconnect_backoff_cap_seconds=60,
        connect_message_stream=connect_factory,
        parse_message=lambda message: [message],
    )

    events = await collect_events(monitor.stream(), count=2)

    assert [event.tx_hash for event in events] == ["tx-backfill", "tx-live"]
    assert rest_monitor.fetch_new_transactions.await_count == 2


@pytest.mark.asyncio
async def test_heartbeat_timeout_forces_reconnect(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_sleep = asyncio.sleep
    monkeypatch.setattr("monitors.asyncio.sleep", AsyncMock(return_value=None))

    async def stalled_stream():
        await real_sleep(0.01)
        yield build_event(tx_hash="never-arrives", block_number=100)

    rest_monitor = build_rest_monitor(tmp_path, AsyncMock(return_value=[]))
    connect_factory = _ConnectFactory([
        [build_event(tx_hash="tx-after-timeout", block_number=101)],
    ])
    monitor = EthWebSocketMonitor(
        rest_monitor=rest_monitor,
        ws_url="wss://eth.example",
        heartbeat_timeout_seconds=0.001,
        reconnect_backoff_cap_seconds=60,
        connect_message_stream=lambda: stalled_stream() if monitor.ws_reconnect_count == 0 else connect_factory(),
        parse_message=lambda message: [message],
    )

    events = await collect_events(monitor.stream(), count=1)

    assert [event.tx_hash for event in events] == ["tx-after-timeout"]
    assert monitor.ws_reconnect_count == 1


@pytest.mark.asyncio
async def test_reconnect_attempt_logs_warning_each_time(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("monitors.asyncio.sleep", AsyncMock(return_value=None))

    warning_mock = Mock()
    monkeypatch.setattr("monitors.logger.warning", warning_mock)

    rest_monitor = build_rest_monitor(tmp_path, AsyncMock(return_value=[]))
    connect_factory = _ConnectFactory([
        _ConnectionDropped("first"),
        _ConnectionDropped("second"),
        [build_event(tx_hash="tx-success", block_number=101)],
    ])
    monitor = EthWebSocketMonitor(
        rest_monitor=rest_monitor,
        ws_url="wss://eth.example",
        heartbeat_timeout_seconds=1,
        reconnect_backoff_cap_seconds=60,
        connect_message_stream=connect_factory,
        parse_message=lambda message: [message],
    )

    await collect_events(monitor.stream(), count=1)

    assert warning_mock.call_count == 2
