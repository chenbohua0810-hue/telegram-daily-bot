# Runtime Runbook

這份 runbook 用於完成目前仍需真實外部環境的驗收項目。

開始前注意：

- 下列步驟會呼叫外部 API：`Binance`、`Anthropic`、`CryptoPanic`、`Etherscan`、`Solscan`、`BscScan`、`Telegram`
- 請先確認 `.env` 已填入真實金鑰
- 建議全程在 paper trading 模式下進行，確認完成後再考慮切 live

## 0. 進入工作目錄

```bash
cd /Users/chenbohua/Downloads/ai_claude/crypto_copy_trader/.worktrees/crypto-copy-trader-implementation/crypto_copy_trader
```

## 1. 確認 `.env` 與路徑設定

檢查關鍵環境變數：

```bash
grep -E '^(PAPER_TRADING|ADDRESSES_DB_PATH|TRADES_DB_PATH|EVENTS_LOG_PATH|TELEGRAM_CHAT_ID)=' .env
```

預期至少包含：

- `PAPER_TRADING=true`
- `ADDRESSES_DB_PATH=data/addresses.db`
- `TRADES_DB_PATH=data/trades.db`
- `EVENTS_LOG_PATH=data/events.jsonl`

如需快速確認 API key 是否已填：

```bash
grep -E '^(BINANCE_API_KEY|BINANCE_API_SECRET|ANTHROPIC_API_KEY|CRYPTOPANIC_API_KEY|ETHERSCAN_API_KEY|SOLSCAN_API_KEY|BSCSCAN_API_KEY|TELEGRAM_BOT_TOKEN)=' .env
```

## 2. 啟動 paper trading 主程式

這一步會呼叫外部 API。

```bash
./.venv/bin/python -m crypto_copy_trader.main
```

驗收目標：

- 程式成功啟動
- 啟動後沒有立即 crash
- 保持執行至少 1 小時

## 3. 驗證 Telegram 啟動通知

主程式啟動時會送出：

```text
crypto copy trader started
```

驗收標準：

- 指定的 Telegram chat 有收到通知

若未收到，優先檢查：

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- bot 是否已加入對應 chat

## 4. 驗證 `events.jsonl` 有真實事件

主程式執行期間，另開終端機檢查：

```bash
wc -l data/events.jsonl
tail -n 5 data/events.jsonl
```

驗收標準：

- `data/events.jsonl` 行數大於 `0`
- 至少有 `1` 筆真實鏈上事件
- 每行均為合法 JSON

## 5. 驗證 1 小時連跑穩定性

讓主程式在 `PAPER_TRADING=true` 下持續執行至少 1 小時。

驗收標準：

- 期間無 crash
- 沒有持續重複的未處理 exception
- `events.jsonl` 持續可寫入

## 6. 切 live 前手動跑一次 wallet scorer

這一步會呼叫外部 API，尤其 `Anthropic`。

先開 Python REPL：

```bash
./.venv/bin/python
```

執行：

```python
import asyncio
from main import build_runtime

runtime = asyncio.run(build_runtime())
asyncio.run(runtime.wallet_scorer.evaluate_all())
asyncio.run(runtime.deps.http.aclose())
asyncio.run(runtime.deps.executor.exchange.close())
```

執行完後檢查 `wallet_history`：

```bash
sqlite3 data/addresses.db "SELECT address, evaluated_at, decision, reasoning FROM wallet_history ORDER BY evaluated_at DESC LIMIT 10;"
```

驗收標準：

- `wallet_history` 至少有 `1` 筆新紀錄

## 7. 24 小時 paper trading 後做 health check

主程式連續跑滿 24 小時後，執行：

```bash
./.venv/bin/python -m verification.runtime_health --hours 24
```

輸出會彙整：

- `event_count`
- `wallet_history_count`
- `snapshot_action_counts`
- `skip_reason_counts`
- `paper_trade_count`
- `avg_estimated_slippage_pct`
- `avg_realized_slippage_pct`

## 8. 如需人工比對原始 SQL

```bash
sqlite3 data/trades.db "SELECT final_action, COUNT(*) FROM decision_snapshots GROUP BY final_action;"
sqlite3 data/trades.db "SELECT skip_reason, COUNT(*) FROM decision_snapshots WHERE final_action='skip' GROUP BY skip_reason;"
sqlite3 data/trades.db "SELECT AVG(realized_slippage_pct), AVG(estimated_slippage_pct) FROM trades WHERE status='paper';"
```

## 建議執行順序

1. 確認 `.env`
2. 確認 `PAPER_TRADING=true`
3. 啟動 `python -m crypto_copy_trader.main`
4. 確認 Telegram 收到啟動通知
5. 確認 `data/events.jsonl` 已寫入事件
6. 連跑 1 小時確認無 crash
7. 手動跑一次 wallet scorer
8. 查 `wallet_history`
9. 跑滿 24 小時後執行 `verification.runtime_health`

## 完成定義

以下條件全部成立，才表示真實環境驗收完成：

- 1 小時 paper trading 無 crash
- Telegram 啟動通知成功送達
- `data/events.jsonl` 至少有 1 筆真實事件
- `wallet_history` 有新增紀錄
- 24 小時 health check 已執行並可讀取結果
