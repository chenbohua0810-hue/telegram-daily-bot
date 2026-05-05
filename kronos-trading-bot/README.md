# Kronos Trading Bot

Paper-only Kronos Binance Spot analysis and simulated trading project.

Version 1 safety boundary:

- Paper trading only.
- No live order placement.
- No Binance private endpoints.
- No API keys, tokens, wallet seeds, or other secrets in repository files.
- `risk_guard` must approve any simulated order before the paper trader can execute it.

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
pytest -q
ruff check .
```

## Default market scope

- Exchange: Binance Spot public market data
- Symbols: BTC/USDT, ETH/USDT
- Interval: 1h candles
- Mode: paper
