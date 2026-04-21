from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Awaitable, Callable

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from models.events import OnChainEvent
from monitors.base import ChainMonitor


PriceFetcher = Callable[[str], Awaitable[Decimal]]


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

        payload = await self._request_transfers(address, from_time)
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
