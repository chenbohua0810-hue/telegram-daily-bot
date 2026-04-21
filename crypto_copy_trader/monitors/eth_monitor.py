from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Awaitable, Callable

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from models.events import OnChainEvent
from monitors.base import ChainMonitor


PriceFetcher = Callable[[str], Awaitable[Decimal]]


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
