from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Iterable
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Awaitable, Callable, Literal

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from models import OnChainEvent
from storage import AddressesRepo, EventLog


logger = logging.getLogger(__name__)

PriceFetcher = Callable[[str], Awaitable[Decimal]]


# ---------------------------------------------------------------------------
# base
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# eth
# ---------------------------------------------------------------------------


class EthMonitor(ChainMonitor):
    chain = "eth"
    _base_url = "https://api.etherscan.io/api"

    def __init__(
        self,
        api_key: str,
        addresses_repo,
        event_log,
        *,
        price_fetcher: PriceFetcher,
        binance_symbols: set[str],
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(api_key, addresses_repo, event_log, client=client)
        self._price_fetcher = price_fetcher
        self._binance_symbols = set(binance_symbols)

    async def fetch_new_transactions(
        self,
        address: str,
        since_block: int | None,
    ) -> list[OnChainEvent]:
        payload = await self._request_transactions(address, since_block or 0)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1) if since_block is None else None
        events: list[OnChainEvent] = []

        for tx in payload.get("result", []):
            event = await self._parse_transaction(tx, address, cutoff)
            if event is not None:
                events.append(event)

        return events

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_fixed(0),
        retry=retry_if_exception_type(httpx.HTTPError),
        reraise=True,
    )
    async def _request_transactions(self, address: str, start_block: int) -> dict:
        response = await self.client.get(
            self._base_url,
            params={
                "module": "account",
                "action": "tokentx",
                "address": address,
                "startblock": start_block,
                "sort": "asc",
                "apikey": self.api_key,
            },
        )
        response.raise_for_status()
        return response.json()

    async def _parse_transaction(
        self,
        tx: dict,
        address: str,
        cutoff: datetime | None,
    ) -> OnChainEvent | None:
        lower_address = address.lower()
        to_address = str(tx.get("to", "")).lower()
        from_address = str(tx.get("from", "")).lower()

        if to_address == "0x0":
            return None

        if to_address == lower_address:
            tx_type = "swap_in"
        elif from_address == lower_address:
            tx_type = "swap_out"
        else:
            return None

        block_time = datetime.fromtimestamp(int(tx["timeStamp"]), tz=timezone.utc)
        if cutoff is not None and block_time < cutoff:
            return None

        token_symbol = str(tx["tokenSymbol"]).upper()
        decimals = int(tx["tokenDecimal"])
        amount_token = Decimal(tx["value"]) / (Decimal(10) ** decimals)
        amount_usd = await self._estimate_amount_usd(token_symbol, amount_token)

        raw = dict(tx)
        raw["block_number"] = int(tx["blockNumber"])

        return OnChainEvent(
            chain=self.chain,
            wallet=address,
            tx_hash=tx["hash"],
            block_time=block_time,
            tx_type=tx_type,
            token_symbol=token_symbol,
            amount_token=amount_token,
            amount_usd=amount_usd,
            raw=raw,
        )

    async def _estimate_amount_usd(self, token_symbol: str, amount_token: Decimal) -> Decimal:
        symbol = f"{token_symbol}/USDT"
        if symbol not in self._binance_symbols:
            return Decimal("0")

        price = await self._price_fetcher(symbol)
        return amount_token * price


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


# ---------------------------------------------------------------------------
# sol
# ---------------------------------------------------------------------------


class SolMonitor(ChainMonitor):
    chain = "sol"
    _base_url = "https://pro-api.solscan.io/v2.0/account/transfer"

    def __init__(
        self,
        api_key: str,
        addresses_repo,
        event_log,
        *,
        price_fetcher: PriceFetcher,
        binance_symbols: set[str],
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(api_key, addresses_repo, event_log, client=client)
        self._price_fetcher = price_fetcher
        self._binance_symbols = set(binance_symbols)

    async def fetch_new_transactions(
        self,
        address: str,
        since_block: int | None,
    ) -> list[OnChainEvent]:
        from_time = since_block
        if from_time is None:
            from_time = int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp())

        try:
            payload = await self._request_transfers(address, from_time)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                logger.warning(
                    "[SolMonitor] API key unauthorised (HTTP %d) for %s... — "
                    "set SOLSCAN_API_KEY to a Pro key for SOL monitoring",
                    exc.response.status_code,
                    address[:8],
                )
                return []
            raise
        events: list[OnChainEvent] = []

        for tx in payload.get("data", []):
            event = await self._parse_transfer(tx, address)
            if event is not None:
                events.append(event)

        return events

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_fixed(0),
        retry=retry_if_exception_type(httpx.HTTPError),
        reraise=True,
    )
    async def _request_transfers(self, address: str, from_time: int) -> dict:
        response = await self.client.get(
            self._base_url,
            params={"address": address, "from_time": from_time},
            headers={"token": self.api_key},
        )
        response.raise_for_status()
        return response.json()

    async def _parse_transfer(self, tx: dict, address: str) -> OnChainEvent | None:
        transfer_type = tx.get("transfer_type")
        decimals = tx.get("token_decimals")

        if transfer_type not in {"in", "out"} or decimals in (None, ""):
            return None

        token_symbol = str(tx["token_symbol"]).upper()
        amount_token = Decimal(tx["amount"]) / (Decimal(10) ** int(decimals))
        amount_usd = await self._estimate_amount_usd(token_symbol, amount_token)
        tx_type = "swap_in" if transfer_type == "in" else "swap_out"
        raw = dict(tx)
        raw["slot"] = int(tx["block_time"])
        raw["solana_slot"] = tx["slot"]

        return OnChainEvent(
            chain=self.chain,
            wallet=address,
            tx_hash=tx["trans_id"],
            block_time=datetime.fromtimestamp(int(tx["block_time"]), tz=timezone.utc),
            tx_type=tx_type,
            token_symbol=token_symbol,
            amount_token=amount_token,
            amount_usd=amount_usd,
            raw=raw,
        )

    async def _estimate_amount_usd(self, token_symbol: str, amount_token: Decimal) -> Decimal:
        symbol = f"{token_symbol}/USDT"
        if symbol not in self._binance_symbols:
            return Decimal("0")

        price = await self._price_fetcher(symbol)
        return amount_token * price


_SOL_MINT = "So11111111111111111111111111111111111111112"
_STABLECOINS = frozenset({"USDC", "USDT", "BUSD", "DAI", "USDS", "PYUSD", "FDUSD"})


def _is_boring_token(symbol: str, address: str) -> bool:
    return symbol in _STABLECOINS or address == _SOL_MINT


class BirdeyeSolMonitor(ChainMonitor):
    """SOL monitor backed by Birdeye public API — replaces Solscan Pro.

    Note: ``since_block`` is interpreted as a unix timestamp (seconds),
    not a Solana slot number, because Birdeye's seek_by_time endpoint
    pages by ``after_time``. ``raw["slot"]`` therefore stores the
    block_unix_time so ``_extract_block_marker`` continues to work.
    """

    chain = "sol"
    _base_url = "https://public-api.birdeye.so/trader/txs/seek_by_time"

    def __init__(
        self,
        api_key: str,
        addresses_repo: AddressesRepo,
        event_log: EventLog,
        *,
        price_fetcher: PriceFetcher,
        binance_symbols: set[str],
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(api_key, addresses_repo, event_log, client=client)
        self._price_fetcher = price_fetcher
        self._binance_symbols = set(binance_symbols)

    async def fetch_new_transactions(
        self,
        address: str,
        since_block: int | None,
    ) -> list[OnChainEvent]:
        after_time = since_block
        if after_time is None:
            after_time = int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp())

        try:
            payload = await self._request_txs(address, after_time)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in (400, 401, 403, 429) or 500 <= status < 600:
                logger.warning(
                    "[BirdeyeSolMonitor] API error %d for %s...",
                    status,
                    address[:8],
                )
                return []
            raise

        items = (payload.get("data") or {}).get("items") or []
        events: list[OnChainEvent] = []
        for tx in items:
            event = await self._parse_swap(tx, address)
            if event is not None:
                events.append(event)
        return events

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_fixed(1),
        retry=retry_if_exception_type(httpx.HTTPError),
        reraise=True,
    )
    async def _request_txs(self, address: str, after_time: int) -> dict:
        response = await self.client.get(
            self._base_url,
            params={"address": address, "tx_type": "swap", "limit": 50, "after_time": after_time},
            headers={"X-API-KEY": self.api_key, "x-chain": "solana"},
        )
        response.raise_for_status()
        return response.json()

    async def _parse_swap(self, tx: dict, address: str) -> OnChainEvent | None:
        ts = tx.get("block_unix_time") or 0
        tx_hash = tx.get("tx_hash") or ""
        if not tx_hash or not ts:
            return None

        base = tx.get("base") or {}
        quote = tx.get("quote") or {}

        base_dir = base.get("type_swap")
        if base_dir == "from":
            sent_side, recv_side = base, quote
        elif base_dir == "to":
            sent_side, recv_side = quote, base
        else:
            return None

        sent_sym = str(sent_side.get("symbol") or "").upper()
        recv_sym = str(recv_side.get("symbol") or "").upper()
        sent_addr = sent_side.get("address") or ""
        recv_addr = recv_side.get("address") or ""

        recv_boring = _is_boring_token(recv_sym, recv_addr)
        sent_boring = _is_boring_token(sent_sym, sent_addr)

        if not recv_boring:
            token_side, tx_type = recv_side, "swap_in"
        elif not sent_boring:
            token_side, tx_type = sent_side, "swap_out"
        else:
            return None

        token_symbol = str(token_side.get("symbol") or "UNKNOWN").upper()
        amount_token = Decimal(str(token_side.get("ui_amount") or 0))
        amount_usd = await self._estimate_amount_usd(token_symbol, amount_token)

        raw = dict(tx)
        raw["slot"] = ts

        return OnChainEvent(
            chain=self.chain,
            wallet=address,
            tx_hash=tx_hash,
            block_time=datetime.fromtimestamp(ts, tz=timezone.utc),
            tx_type=tx_type,
            token_symbol=token_symbol,
            amount_token=amount_token,
            amount_usd=amount_usd,
            raw=raw,
        )

    async def _estimate_amount_usd(self, token_symbol: str, amount_token: Decimal) -> Decimal:
        symbol = f"{token_symbol}/USDT"
        if symbol not in self._binance_symbols:
            return Decimal("0")
        try:
            price = await self._price_fetcher(symbol)
        except httpx.HTTPError as exc:
            logger.warning(
                "[BirdeyeSolMonitor] price fetch failed for %s: %s", symbol, exc
            )
            return Decimal("0")
        return amount_token * price


class SolWebSocketMonitor(WebSocketChainMonitor):
    chain = "sol"

    def __init__(
        self,
        *,
        rest_monitor: SolMonitor,
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
            raise NotImplementedError("Helius websocket connection is not configured")
        return self._connect_message_stream_override()

    async def _parse_message(self, message: Any) -> list[OnChainEvent]:
        if self._parse_message_override is None:
            return []
        return self._parse_message_override(message)


# ---------------------------------------------------------------------------
# bsc
# ---------------------------------------------------------------------------


class BscMonitor(EthMonitor):
    chain = "bsc"
    _base_url = "https://api.bscscan.com/api"


class BscWebSocketMonitor(WebSocketChainMonitor):
    chain = "bsc"

    def __init__(
        self,
        *,
        rest_monitor: BscMonitor,
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
            raise NotImplementedError("QuickNode websocket connection is not configured")
        return self._connect_message_stream_override()

    async def _parse_message(self, message: Any) -> list[OnChainEvent]:
        if self._parse_message_override is None:
            return []
        return self._parse_message_override(message)
