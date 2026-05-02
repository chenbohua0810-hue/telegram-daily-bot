from __future__ import annotations

from signals.symbol_mapper import map_to_binance


def test_maps_known_wrapped_token_by_contract_address() -> None:
    symbol = map_to_binance(
        "eth",
        "0xC02AAA39B223FE8D0A0E5C4F27EAD9083C756CC2",
        "WETH",
    )

    assert symbol == "ETH/USDT"


def test_rejects_unknown_contract_even_when_symbol_matches_blue_chip() -> None:
    symbol = map_to_binance(
        "eth",
        "0x000000000000000000000000000000000000dead",
        "BTC",
    )

    assert symbol is None


def test_maps_native_asset_without_contract_address() -> None:
    symbol = map_to_binance("sol", "", "SOL")

    assert symbol == "SOL/USDT"
