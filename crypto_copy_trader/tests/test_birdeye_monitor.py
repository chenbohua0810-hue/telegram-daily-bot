from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from monitors import BirdeyeSolMonitor
from storage import AddressesRepo


_SOL_MINT = "So11111111111111111111111111111111111111112"
_USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
_JUP_MINT = "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"
_BONK_MINT = "DezXAZ8z7PnrnRJjz3VjVUL7JV2W6APW3w1pPB263wW"


def _make_tx(
    *,
    tx_hash: str = "tx-1",
    ts: int = 1_776_000_000,
    base: dict | None = None,
    quote: dict | None = None,
) -> dict:
    return {
        "tx_hash": tx_hash,
        "block_unix_time": ts,
        "base": base or {},
        "quote": quote or {},
    }


def _make_monitor(
    repo: AddressesRepo,
    *,
    payload: dict | None = None,
    handler=None,
    binance_symbols: set[str] | None = None,
    price_map: dict[str, Decimal] | None = None,
) -> tuple[BirdeyeSolMonitor, httpx.AsyncClient]:
    if handler is None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code=200, json=payload or {})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    prices = price_map or {"JUP/USDT": Decimal("1"), "BONK/USDT": Decimal("0.00002")}
    monitor = BirdeyeSolMonitor(
        api_key="key",
        addresses_repo=repo,
        event_log=Mock(),
        price_fetcher=AsyncMock(side_effect=lambda symbol: prices[symbol]),
        binance_symbols=binance_symbols if binance_symbols is not None else set(prices),
        client=client,
    )
    return monitor, client


@pytest.mark.asyncio
async def test_parse_swap_base_from_picks_quote_as_token(tmp_path) -> None:
    repo = AddressesRepo(str(tmp_path / "addresses.db"))
    payload = {
        "data": {
            "items": [
                _make_tx(
                    tx_hash="buy-jup",
                    ts=1_776_000_100,
                    base={
                        "type_swap": "from",
                        "symbol": "USDC",
                        "address": _USDC_MINT,
                        "ui_amount": 100,
                    },
                    quote={
                        "type_swap": "to",
                        "symbol": "JUP",
                        "address": _JUP_MINT,
                        "ui_amount": 50,
                    },
                ),
            ]
        }
    }
    monitor, client = _make_monitor(repo, payload=payload)
    try:
        events = await monitor.fetch_new_transactions("wallet", since_block=1_776_000_000)
    finally:
        await client.aclose()

    assert len(events) == 1
    event = events[0]
    assert event.tx_hash == "buy-jup"
    assert event.tx_type == "swap_in"
    assert event.token_symbol == "JUP"
    assert event.amount_token == Decimal("50")
    assert event.amount_usd == Decimal("50")
    assert event.raw["slot"] == 1_776_000_100


@pytest.mark.asyncio
async def test_parse_swap_quote_from_picks_base_as_sent_token(tmp_path) -> None:
    repo = AddressesRepo(str(tmp_path / "addresses.db"))
    payload = {
        "data": {
            "items": [
                _make_tx(
                    tx_hash="sell-bonk",
                    base={
                        "type_swap": "to",
                        "symbol": "USDT",
                        "address": "USDTmint",
                        "ui_amount": 20,
                    },
                    quote={
                        "type_swap": "from",
                        "symbol": "BONK",
                        "address": _BONK_MINT,
                        "ui_amount": 1_000_000,
                    },
                ),
            ]
        }
    }
    monitor, client = _make_monitor(repo, payload=payload)
    try:
        events = await monitor.fetch_new_transactions("wallet", since_block=1)
    finally:
        await client.aclose()

    assert len(events) == 1
    assert events[0].tx_type == "swap_out"
    assert events[0].token_symbol == "BONK"
    assert events[0].amount_usd == Decimal("1000000") * Decimal("0.00002")


@pytest.mark.asyncio
async def test_parse_swap_skips_stable_to_stable(tmp_path) -> None:
    repo = AddressesRepo(str(tmp_path / "addresses.db"))
    payload = {
        "data": {
            "items": [
                _make_tx(
                    tx_hash="stable-rotate",
                    base={
                        "type_swap": "from",
                        "symbol": "USDC",
                        "address": _USDC_MINT,
                        "ui_amount": 100,
                    },
                    quote={
                        "type_swap": "to",
                        "symbol": "USDT",
                        "address": "USDTmint",
                        "ui_amount": 100,
                    },
                ),
            ]
        }
    }
    monitor, client = _make_monitor(repo, payload=payload)
    try:
        events = await monitor.fetch_new_transactions("wallet", since_block=1)
    finally:
        await client.aclose()

    assert events == []


@pytest.mark.asyncio
async def test_parse_swap_skips_unknown_type_swap(tmp_path) -> None:
    repo = AddressesRepo(str(tmp_path / "addresses.db"))
    payload = {
        "data": {
            "items": [
                _make_tx(
                    base={"symbol": "USDC", "address": _USDC_MINT, "ui_amount": 100},
                    quote={"symbol": "JUP", "address": _JUP_MINT, "ui_amount": 50},
                ),
            ]
        }
    }
    monitor, client = _make_monitor(repo, payload=payload)
    try:
        events = await monitor.fetch_new_transactions("wallet", since_block=1)
    finally:
        await client.aclose()

    assert events == []


@pytest.mark.asyncio
async def test_parse_swap_skips_when_tx_hash_or_ts_missing(tmp_path) -> None:
    repo = AddressesRepo(str(tmp_path / "addresses.db"))
    payload = {
        "data": {
            "items": [
                {"tx_hash": "", "block_unix_time": 1, "base": {}, "quote": {}},
                {"tx_hash": "x", "block_unix_time": 0, "base": {}, "quote": {}},
            ]
        }
    }
    monitor, client = _make_monitor(repo, payload=payload)
    try:
        events = await monitor.fetch_new_transactions("wallet", since_block=1)
    finally:
        await client.aclose()

    assert events == []


@pytest.mark.asyncio
async def test_fetch_returns_empty_on_auth_error(tmp_path) -> None:
    repo = AddressesRepo(str(tmp_path / "addresses.db"))

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=401, json={"message": "unauthorized"})

    monitor, client = _make_monitor(repo, handler=handler)
    try:
        events = await monitor.fetch_new_transactions("wallet", since_block=1)
    finally:
        await client.aclose()

    assert events == []


@pytest.mark.asyncio
async def test_fetch_returns_empty_on_5xx(tmp_path) -> None:
    repo = AddressesRepo(str(tmp_path / "addresses.db"))
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(status_code=502, json={"message": "bad gateway"})

    monitor, client = _make_monitor(repo, handler=handler)
    try:
        events = await monitor.fetch_new_transactions("wallet", since_block=1)
    finally:
        await client.aclose()

    assert events == []
    assert calls["count"] >= 1


@pytest.mark.asyncio
async def test_estimate_amount_usd_swallows_price_http_error(tmp_path) -> None:
    repo = AddressesRepo(str(tmp_path / "addresses.db"))
    payload = {
        "data": {
            "items": [
                _make_tx(
                    base={
                        "type_swap": "from",
                        "symbol": "USDC",
                        "address": _USDC_MINT,
                        "ui_amount": 100,
                    },
                    quote={
                        "type_swap": "to",
                        "symbol": "JUP",
                        "address": _JUP_MINT,
                        "ui_amount": 50,
                    },
                ),
            ]
        }
    }

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, json=payload)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def failing_price(_symbol: str) -> Decimal:
        raise httpx.HTTPError("network down")

    monitor = BirdeyeSolMonitor(
        api_key="key",
        addresses_repo=repo,
        event_log=Mock(),
        price_fetcher=failing_price,
        binance_symbols={"JUP/USDT"},
        client=client,
    )
    try:
        events = await monitor.fetch_new_transactions("wallet", since_block=1)
    finally:
        await client.aclose()

    assert len(events) == 1
    assert events[0].amount_usd == Decimal("0")


@pytest.mark.asyncio
async def test_request_uses_after_time_param(tmp_path) -> None:
    repo = AddressesRepo(str(tmp_path / "addresses.db"))
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        seen["headers"] = dict(request.headers)
        return httpx.Response(status_code=200, json={"data": {"items": []}})

    monitor, client = _make_monitor(repo, handler=handler)
    try:
        await monitor.fetch_new_transactions("wallet", since_block=1_776_000_000)
    finally:
        await client.aclose()

    assert seen["params"]["address"] == "wallet"
    assert seen["params"]["after_time"] == "1776000000"
    assert seen["params"]["tx_type"] == "swap"
    assert seen["headers"]["x-api-key"] == "key"
    assert seen["headers"]["x-chain"] == "solana"
