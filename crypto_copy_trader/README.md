# Crypto Copy Trader

追蹤鏈上高勝率、大資金地址的操作，在 Binance 執行對應跟單。鏈上只做信號偵測，不直接上鏈交易。

## Architecture

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                         crypto_copy_trader/                             │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │ Layer 1: Chain Monitor                                            │  │
│  │ REST monitors + optional WebSocket monitors with reconnect/backfill│  │
│  │ Eth / Sol / BSC                                                   │  │
│  └───────────────────────────────┬───────────────────────────────────┘  │
│                                  ↓                                      │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │ Layer 2: Signal Pipeline                                          │  │
│  │ QuantFilter → PriorityRouter → LLM Routing                        │  │
│  │   P0: Claude direct                                               │  │
│  │   P1: direct copy trade                                            │  │
│  │   P2: BatchScorer → fallback backends                              │  │
│  │   P3: skip                                                         │  │
│  └───────────────────────────────┬───────────────────────────────────┘  │
│                                  ↓                                      │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │ Layer 3: Execution                                                │  │
│  │ PositionSizer → RiskGuard → SlippageFeeEstimator → BinanceExecutor│  │
│  └───────────────────────────────┬───────────────────────────────────┘  │
│                                  ↓                                      │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │ Layer 4: Analytics & Health                                       │  │
│  │ TradeLogger → PerformanceTracker → TelegramNotifier               │  │
│  │ verification.runtime_health                                       │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
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
- `LLM_PRIMARY_NAME`
- `LLM_PRIMARY_BASE_URL`
- `LLM_PRIMARY_MODEL`
- `LLM_PRIMARY_API_KEY`
- `LLM_SECONDARY_NAME`
- `LLM_SECONDARY_BASE_URL`
- `LLM_SECONDARY_MODEL`
- `LLM_SECONDARY_API_KEY`
- `BATCH_WINDOW_SECONDS`
- `BATCH_MAX_SIZE`
- `BATCH_MAX_INPUT_TOKENS`
- `HIGH_VALUE_USD_THRESHOLD`
- `P1_HIGH_TRUST_MIN_USD`
- `P1_HIGH_TRUST_RECENT_WINRATE`
- `USE_WEBSOCKET`
- `ETH_WSS_URL`
- `SOL_WSS_URL`
- `BSC_WSS_URL`
- `WS_HEARTBEAT_TIMEOUT_SECONDS`
- `WS_RECONNECT_BACKOFF_CAP_SECONDS`
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
