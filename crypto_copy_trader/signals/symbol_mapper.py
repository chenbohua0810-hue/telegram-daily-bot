from __future__ import annotations

from typing import Final


ETH_WETH_ADDRESS: Final = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
ETH_WBTC_ADDRESS: Final = "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599"
ETH_PEPE_ADDRESS: Final = "0x6982508145454ce325ddbe47a25d4ec3d2311933"
ETH_UNI_ADDRESS: Final = "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984"
ETH_LINK_ADDRESS: Final = "0x514910771af9ca656af840dff83e8264ecf986ca"
ETH_USDC_ADDRESS: Final = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
ETH_USDT_ADDRESS: Final = "0xdac17f958d2ee523a2206206994597c13d831ec7"
SOL_WSOL_ADDRESS: Final = "So11111111111111111111111111111111111111112"
SOL_JUP_ADDRESS: Final = "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"
SOL_BONK_ADDRESS: Final = "DezXAZ8z7PnrnRJjz3VjVUL7JV2W6APW3w1pPB263wW"

KNOWN_TOKEN_MAP: Final[dict[tuple[str, str], str]] = {
    ("eth", ETH_WETH_ADDRESS): "ETH/USDT",
    ("eth", ETH_WBTC_ADDRESS): "BTC/USDT",
    ("eth", ETH_PEPE_ADDRESS): "PEPE/USDT",
    ("eth", ETH_UNI_ADDRESS): "UNI/USDT",
    ("eth", ETH_LINK_ADDRESS): "LINK/USDT",
    ("eth", ETH_USDC_ADDRESS): "USDC/USDT",
    ("eth", ETH_USDT_ADDRESS): "USDT/USDT",
    ("sol", SOL_WSOL_ADDRESS): "SOL/USDT",
    ("sol", SOL_JUP_ADDRESS): "JUP/USDT",
    ("sol", SOL_BONK_ADDRESS): "BONK/USDT",
}


def map_to_binance(chain: str, contract_address: str, token_symbol: str) -> str | None:
    normalized_chain = chain.lower().strip()
    normalized_address = contract_address.strip()
    if normalized_chain in {"eth", "bsc"}:
        normalized_address = normalized_address.lower()

    mapped_symbol = KNOWN_TOKEN_MAP.get((normalized_chain, normalized_address))
    if mapped_symbol is not None:
        return mapped_symbol

    return _map_native_asset(normalized_chain, normalized_address, token_symbol)


def _map_native_asset(chain: str, contract_address: str, token_symbol: str) -> str | None:
    if contract_address:
        return None

    native_symbols = {
        ("eth", "ETH"): "ETH/USDT",
        ("bsc", "BNB"): "BNB/USDT",
        ("sol", "SOL"): "SOL/USDT",
    }
    return native_symbols.get((chain, token_symbol.upper().strip()))
