# Crypto Copy Trader

追蹤鏈上高勝率、大資金地址的操作，在 Binance 執行對應跟單。鏈上只做信號偵測，不直接上鏈交易。

## Architecture

```text
┌─────────────────────────────────────────────────────────────────┐
│                  crypto_copy_trader/                            │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Layer 1: Chain Monitor                                  │   │
│  │  EthMonitor   SolanaMonitor   BSCMonitor                 │   │
│  │       └──────────┬──────────────┘                        │   │
│  └──────────────────┼───────────────────────────────────────┘   │
│                     ↓                                           │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Layer 2: Signal Pipeline                                │   │
│  │  QuantFilter → AIScorer → SlippageFeeEstimator           │   │
│  └──────────────────┬───────────────────────────────────────┘   │
│                     ↓                                           │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Layer 3: Execution                                      │   │
│  │  PositionSizer → BinanceExecutor → RiskGuard             │   │
│  └──────────────────┬───────────────────────────────────────┘   │
│                     ↓                                           │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Layer 4: Analytics & Notifier                           │   │
│  │  TradeLogger → PerformanceTracker → TelegramNotifier     │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Run

```bash
python -m crypto_copy_trader.main
```

預設為 paper trading。首次啟動前請確認 `.env` 內所有 API keys 與 Telegram 設定都已填入。

## Environment Variables

所有環境變數都列在 [.env.example](.env.example)。

重點欄位：

- `PAPER_TRADING=true`
- `BINANCE_API_KEY`
- `BINANCE_API_SECRET`
- `ANTHROPIC_API_KEY`
- `CRYPTOPANIC_API_KEY`
- `ETHERSCAN_API_KEY`
- `SOLSCAN_API_KEY`
- `BSCSCAN_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `ADDRESSES_DB_PATH`
- `TRADES_DB_PATH`
- `EVENTS_LOG_PATH`

## Paper To Live

1. 先確認 paper trading 已完整跑過驗收 checklist。
2. 在 `.env` 將 `PAPER_TRADING=false`。
3. 重新啟動 `python -m crypto_copy_trader.main`。
4. 上線前先手動跑一次 wallet scorer，確認 `addresses.db` 有 history 紀錄。

## Test

```bash
pytest
pytest --cov
python -m verification.runtime_health --hours 24
```

詳細驗收步驟見 [docs/verification-checklist.md](docs/verification-checklist.md)。
