from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from monitors import SolMonitor
from storage import AddressesRepo


def _fixture_path(name: str) -> Path:
    return Path(__file__).parent / "fixtures" / name


@pytest.mark.asyncio
async def test_sol_monitor_parses_transfers(tmp_path: pytest.TempPathFactory) -> None:
    db_path = tmp_path / "addresses.db"
    repo = AddressesRepo(str(db_path))
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            status_code=200,
            json=json.loads(_fixture_path("sol_tx_sample.json").read_text(encoding="utf-8")),
        )
    )
    client = httpx.AsyncClient(transport=transport)
    price_map = {
        "SOL/USDT": Decimal("150"),
        "JUP/USDT": Decimal("1"),
        "BONK/USDT": Decimal("0.00002"),
    }
    monitor = SolMonitor(
        api_key="key",
        addresses_repo=repo,
        event_log=Mock(),
        price_fetcher=AsyncMock(side_effect=lambda symbol: price_map[symbol]),
        binance_symbols=set(price_map),
        client=client,
    )

    try:
        events = await monitor.fetch_new_transactions("sol-wallet", since_block=100)
    finally:
        await client.aclose()

    assert len(events) == 3
    assert events[0].tx_type == "swap_in"
    assert events[1].tx_type == "swap_out"
    assert events[2].token_symbol == "BONK"


@pytest.mark.asyncio
async def test_sol_monitor_filters_invalid_token_decimals(tmp_path: pytest.TempPathFactory) -> None:
    db_path = tmp_path / "addresses.db"
    repo = AddressesRepo(str(db_path))
    payload = {
        "success": True,
        "data": [
            {
                "slot": 100,
                "block_time": 1776772800,
                "trans_id": "sol-skip",
                "from_address": "a",
                "to_address": "sol-wallet",
                "token_symbol": "NFT",
                "amount": "1",
                "token_decimals": None,
                "transfer_type": "in",
            },
            {
                "slot": 101,
                "block_time": 1776772860,
                "trans_id": "sol-keep",
                "from_address": "a",
                "to_address": "sol-wallet",
                "token_symbol": "SOL",
                "amount": "1000000000",
                "token_decimals": 9,
                "transfer_type": "in",
            },
        ],
    }
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(status_code=200, json=payload))
    )
    monitor = SolMonitor(
        api_key="key",
        addresses_repo=repo,
        event_log=Mock(),
        price_fetcher=AsyncMock(return_value=Decimal("150")),
        binance_symbols={"SOL/USDT"},
        client=client,
    )

    try:
        events = await monitor.fetch_new_transactions("sol-wallet", since_block=100)
    finally:
        await client.aclose()

    assert [event.tx_hash for event in events] == ["sol-keep"]


@pytest.mark.asyncio
async def test_sol_monitor_retry_on_5xx(tmp_path: pytest.TempPathFactory) -> None:
    db_path = tmp_path / "addresses.db"
    repo = AddressesRepo(str(db_path))
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(status_code=500, json={"success": False, "data": []})

        return httpx.Response(
            status_code=200,
            json=json.loads(_fixture_path("sol_tx_sample.json").read_text(encoding="utf-8")),
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monitor = SolMonitor(
        api_key="key",
        addresses_repo=repo,
        event_log=Mock(),
        price_fetcher=AsyncMock(return_value=Decimal("150")),
        binance_symbols={"SOL/USDT", "JUP/USDT", "BONK/USDT"},
        client=client,
    )

    try:
        events = await monitor.fetch_new_transactions("sol-wallet", since_block=100)
    finally:
        await client.aclose()

    assert len(events) == 3
    assert calls["count"] == 2
