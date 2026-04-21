from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from monitors.bsc_monitor import BscMonitor
from storage.addresses_repo import AddressesRepo


def _fixture_path(name: str) -> Path:
    return Path(__file__).parent / "fixtures" / name


@pytest.mark.asyncio
async def test_bsc_monitor_parses_tokentx(tmp_path: pytest.TempPathFactory) -> None:
    db_path = tmp_path / "addresses.db"
    repo = AddressesRepo(str(db_path))
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                status_code=200,
                json=json.loads(_fixture_path("bsc_tx_sample.json").read_text(encoding="utf-8")),
            )
        )
    )
    price_map = {
        "BNB/USDT": Decimal("600"),
        "CAKE/USDT": Decimal("2"),
        "XVS/USDT": Decimal("8"),
    }
    monitor = BscMonitor(
        api_key="key",
        addresses_repo=repo,
        event_log=Mock(),
        price_fetcher=AsyncMock(side_effect=lambda symbol: price_map[symbol]),
        binance_symbols=set(price_map),
        client=client,
    )

    try:
        events = await monitor.fetch_new_transactions("0xbsc123", since_block=100)
    finally:
        await client.aclose()

    assert len(events) == 3
    assert events[0].chain == "bsc"
    assert events[1].tx_type == "swap_out"


@pytest.mark.asyncio
async def test_bsc_monitor_filters_contract_txs(tmp_path: pytest.TempPathFactory) -> None:
    db_path = tmp_path / "addresses.db"
    repo = AddressesRepo(str(db_path))
    payload = {
        "status": "1",
        "message": "OK",
        "result": [
            {
                "blockNumber": "201",
                "timeStamp": "1776772800",
                "hash": "0xburn",
                "from": "0xaaa",
                "to": "0x0",
                "value": "1000000000000000000",
                "tokenDecimal": "18",
                "tokenSymbol": "BNB",
            },
            {
                "blockNumber": "202",
                "timeStamp": "1776772860",
                "hash": "0xkeep",
                "from": "0xaaa",
                "to": "0xbsc123",
                "value": "1000000000000000000",
                "tokenDecimal": "18",
                "tokenSymbol": "BNB",
            },
        ],
    }
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(status_code=200, json=payload))
    )
    monitor = BscMonitor(
        api_key="key",
        addresses_repo=repo,
        event_log=Mock(),
        price_fetcher=AsyncMock(return_value=Decimal("600")),
        binance_symbols={"BNB/USDT"},
        client=client,
    )

    try:
        events = await monitor.fetch_new_transactions("0xbsc123", since_block=100)
    finally:
        await client.aclose()

    assert [event.tx_hash for event in events] == ["0xkeep"]


@pytest.mark.asyncio
async def test_bsc_monitor_retry_on_5xx(tmp_path: pytest.TempPathFactory) -> None:
    db_path = tmp_path / "addresses.db"
    repo = AddressesRepo(str(db_path))
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(status_code=500, json={"status": "0", "result": []})

        return httpx.Response(
            status_code=200,
            json=json.loads(_fixture_path("bsc_tx_sample.json").read_text(encoding="utf-8")),
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monitor = BscMonitor(
        api_key="key",
        addresses_repo=repo,
        event_log=Mock(),
        price_fetcher=AsyncMock(return_value=Decimal("600")),
        binance_symbols={"BNB/USDT", "CAKE/USDT", "XVS/USDT"},
        client=client,
    )

    try:
        events = await monitor.fetch_new_transactions("0xbsc123", since_block=100)
    finally:
        await client.aclose()

    assert len(events) == 3
    assert calls["count"] == 2
