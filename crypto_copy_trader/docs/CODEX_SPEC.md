# Codex 實作規格書 — Profit Optimization

> 目標：把目前可能 break-even 的 crypto copy trader 改造成可獲利系統。
> 交易場所：**只用 Binance Spot**（不碰鏈上 DEX、不碰永續/合約）。
> 開發原則：每個 Task 是獨立 PR，先寫測試（pytest）再實作，覆蓋率 ≥80%。

---

## ⚠️ 全域前置條件（每個 Task 都要遵守）

### A. 符號對應（Symbol Mapping）— 這是最容易出錯的地方
鏈上 token 的 symbol **不等於** Binance 的交易對代號：
- `WETH` (ETH 鏈) → Binance `ETH/USDT`
- `WBTC` (ETH 鏈) → Binance `BTC/USDT`
- `wstETH`, `stETH` → Binance 沒有，**直接 skip**
- `WSOL` (SOL 鏈) → Binance `SOL/USDT`
- 大多數 SOL meme coin（如 `BONK`, `WIF`, `POPCAT`）→ 部分 Binance 有，部分沒有
- **同名不同物**：鏈上有些垃圾 token 故意叫 `USDT` / `BTC`，必須用 contract address 驗證，**不能只比對 symbol 字串**

**Codex 動作**：
1. 在 `models.py` 新增 `OnChainEvent.token_address: str`（必填）
2. 在 `monitors.py` 所有 parse 邏輯填入 contract address
3. 新增 `signals/symbol_mapper.py`：
   - 維護一份 `KNOWN_TOKEN_MAP: dict[(chain, contract_address), binance_symbol]` 寫死在檔案內（手動維護 top 200 token 即可）
   - 提供 `map_to_binance(chain, contract_address, token_symbol) -> str | None`
   - 找不到回 `None`，呼叫端 skip
4. 在 `quant_filter` 把 `f"{event.token_symbol}/USDT"` 改成 `map_to_binance(...)` 結果

### B. Binance Trading Rules — 不處理會被 API reject
Binance 每個交易對有三個必查 filter：
- `LOT_SIZE.stepSize`：數量必須是 stepSize 的整數倍（`BTC/USDT` 是 0.00001）
- `PRICE_FILTER.tickSize`：價格必須是 tickSize 的整數倍
- `MIN_NOTIONAL.minNotional`：訂單金額下限（通常 5-10 USDT）

**Codex 動作**：
1. 在 `BinanceExecutor` 新增 `load_markets` 後快取每個 symbol 的 `(stepSize, tickSize, minNotional)` 到 `self._symbol_filters`
2. 新增 `_quantize(symbol, quantity, price) -> tuple[Decimal, Decimal]`，套用三個 filter
3. 所有下單前都先 quantize，量化後 < minNotional 直接放棄
4. 寫測試：用 ccxt market 結構模擬 BTC/USDT、SHIB/USDT（極小單位）、PEPE/USDT 三個案例

### C. Rate Limit
Binance Spot REST：**1200 weight / minute**（每帳號 IP）。
- `fetch_ticker` = 2, `fetch_order_book(limit=20)` = 5, `create_order` = 1, `fetch_balance` = 10
- 60 個錢包 × 每分鐘 fetch_ticker + orderbook 就 = 420 weight，再加下單和健康檢查很容易爆

**Codex 動作**：
1. 新增 `execution_helpers.py` → `RateLimiter(weight_per_min=1000)`（留 200 buffer）
2. 包裝所有 ccxt 呼叫經 `RateLimiter.acquire(weight)`
3. 超過時 `await asyncio.sleep(剩餘秒數)`，**不要 raise**

### D. 部位狀態持久化
重啟必須能恢復。目前 `Portfolio` 是 in-memory dict，重啟會忘記持有部位的 `source_wallet` 和 `entry_time`。

**Codex 動作**：
1. 在 `storage.py` 新增 `PositionsRepo`：`save_position`, `delete_position`, `load_all_positions`
2. SQLite schema：`(symbol, quantity, avg_entry_price, entry_time, source_wallet, peak_price, last_update)`
3. `main()` 啟動時 load 進 `Portfolio`，每次 fill / exit 後同步寫回

---

## 🚨 TASK 1（最高優先）— Mirror Exit 跟賣邏輯

### 目標
被跟蹤錢包賣出時，立刻平掉同 token 的同向部位。**這是 copy trading 賺錢與否的關鍵。**

### 規則
1. **觸發條件**：收到 `OnChainEvent` 且 `tx_type == "swap_out"` 且 `event.wallet == position.source_wallet` 且 `position.symbol == map_to_binance(event)`
2. **平倉比例**：
   - 若該錢包賣出 ≥30% 該 token 持有（需 Birdeye/Etherscan 查持倉變化）→ 我方平 100%
   - 若 <30% → 我方平 50%（部分減倉）
3. **執行**：直接 market sell（exit 不可等 limit，跑慢一秒可能損失 1%）
4. **競態保護**：用 `asyncio.Lock` per `symbol`，避免 entry 和 exit 同時打到同一個 symbol

### 邊界情況
- 該 wallet 是「分批出場」：用 30 分鐘滾動視窗累計賣出 token 數量，達 ≥30% 才平 100%
- 我方無對應部位：log + skip，不要 raise
- 鏈上錢包賣到的 token（如 `swap_out USDC → ETH`）方向是「買 ETH」，不是「賣 ETH」。`monitors.py` 的 `_parse_swap` 必須正確區分「賣出標的 token」vs「賣出計價 token」

### Files
- `monitors.py`: 確保 swap_out 事件 emit 正確方向
- `signals/exit_router.py` (新): `should_mirror_exit(event, position) -> ExitDecision`
- `execution.py`: 新增 `BinanceExecutor.execute_exit(symbol, fraction)`
- `main.py` `process_event`: 在最前面分流，`tx_type == "swap_out"` 走 exit pipeline

### 測試
- `test_exit_full_when_wallet_sells_30pct`
- `test_exit_partial_when_wallet_sells_under_30pct`
- `test_exit_skips_when_no_matching_position`
- `test_exit_lock_prevents_concurrent_buy`

### 驗收
- 模擬：錢包 A 在 t=0 buy 1000 USDT 的 PEPE，你跟單 100 USDT；t=60s 錢包 A 賣 50% PEPE，你的 PEPE 部位也減 50%
- Telegram 收到 `[EXIT] symbol=PEPE/USDT fraction=0.5 reason=mirror_wallet_0x...`

---

## 🚨 TASK 2 — Hard Stop Loss / Take Profit / Time Stop

### 目標
任何已開倉部位都必須有強制出場條件，不依賴鏈上信號。

### 規則
**新增 background loop** `position_monitor_loop`，每 30 秒掃描所有 open positions：

| 條件 | 行為 |
|------|------|
| `current_price <= avg_entry × 0.92` | 市價平倉 100%，reason=`stop_loss_-8pct` |
| `peak_price >= avg_entry × 1.20` 後從 peak 回撤 ≥30% | 市價平倉 100%，reason=`trailing_stop` |
| `now - entry_time >= 48h` 且 `unrealized_pnl_pct < 2%` | 市價平倉 100%，reason=`time_stop_no_progress` |
| `now - entry_time >= 7d` | 強制平倉，reason=`max_hold_period` |

`peak_price` 必須持久化到 `PositionsRepo`，每次掃描更新。

### 邊界
- 同一部位**不可同時觸發 mirror exit + stop loss**：用 `asyncio.Lock` per symbol
- 平倉失敗（網路錯誤）：retry 3 次，每次 backoff 5/10/20 秒，**最後仍失敗發 Telegram alert + 寫進 `data/exit_failures.jsonl`**（人工介入）
- BTC 24h 跌 >10% 時，全部 stop loss 收緊到 -5%（market regime adjustment）

### Files
- `execution.py`: 新增 `position_stop_check(position, current_price, btc_24h_change) -> StopAction | None`
- `main.py`: 新增 `position_monitor_loop(executor, positions_repo, notifier)`，跟 `wallet_scorer_loop` 一樣 background asyncio task

### 測試
- `test_stop_loss_triggers_at_minus_8pct`
- `test_trailing_stop_triggers_after_peak_then_drawdown`
- `test_time_stop_triggers_after_48h_flat`
- `test_market_regime_tightens_stop_when_btc_crashes`

---

## 🚨 TASK 3 — Latency 降低

### 3a. WebSocket for ETH（最大效益）
目前 `ETH_WSS_URL` 預設空字串，walks back to REST polling。

**Codex 動作**：
- README 加說明：免費 Alchemy account → wss endpoint
- `monitors.py` 的 `EthWebSocketMonitor` 已存在，確保 `USE_WEBSOCKET=True` 時優先用 WS，REST 只當 backfill
- 加健康檢查：WS 斷線 >120s 自動降級回 60s polling 並發 Telegram 警告

### 3b. 高 Trust 錢包 polling 加速
**Codex 動作**：
- `monitors.py` REST monitor 把 `addresses` 分兩組：`high_trust` / `others`
- `high_trust` poll interval = 15 秒，`others` = 60 秒
- 分組標準：`wallet.trust_level == "high"` 且 `wallet.recent_win_rate >= 0.60`

### 3c. P0 不走 LLM
看 `main.py` line 119-128，P0 還在打 Claude，加了 1-3 秒延遲。**對高 trust + 高金額信號這 3 秒是致命的。**

**Codex 動作**：
- `process_event`：`priority.level == "P0"` 直接組 `AIScore(confidence_score=100, recommendation="execute", reasoning="P0_direct")`，**完全跳過 LLM**
- LLM 只用在 P2（不確定區）

### 測試
- `test_p0_skips_llm_call`：mock claude_backend，斷言 0 次呼叫
- `test_high_trust_wallet_uses_15s_interval`

---

## 🚨 TASK 4 — Maker Limit Order 取代 Market Order

### 目標
進場全部改 limit order 掛在 mid + 5bps（極微 aggressive maker），1.5 秒未成交才退回 market。**單次來回省 ~50 bps。**

### 規則
進場流程：
1. `fetch_orderbook` 取 `bid[0]`、`ask[0]`
2. `mid = (bid + ask) / 2`
3. **買單**：limit price = `mid × (1 + 0.0005)`（aggressive 但仍可能 maker）
4. **賣單**：limit price = `mid × (1 - 0.0005)`
5. 用 `postOnly=True` 確保是 maker（被拒就代表會吃單，那就退回 market）
6. 等 1.5 秒，若未成交 → cancel → market order

**注意**：mirror exit 和 stop loss **永遠用 market**，不要省這 5 bps，平倉慢一秒可能多虧 50 bps。

### 邊界
- 部分成交：把已成交部分記錄為 fill，剩餘部分 cancel 後 market
- `postOnly` 被 reject (-2010)：直接降到 market
- spread > 50 bps：判定流動性差，跳過這筆進場（reason=`wide_spread`）

### Files
- `execution.py` `BinanceExecutor.execute`：分流 entry / exit，entry 走新 `_execute_with_maker_first`，exit 走 `_execute_market`

### 測試
- `test_maker_first_then_market_fallback`
- `test_post_only_rejection_falls_back_to_market`
- `test_wide_spread_skips_entry`
- `test_exit_always_uses_market`

---

## 🚨 TASK 5 — Trust-Based Position Sizing

### 目標
取代目前 flat 10%，依 wallet trust 動態調整。

### 規則
| Trust | Base % of portfolio | 條件 |
|-------|---------------------|------|
| high | 6% | `recent_win_rate ≥ 0.60` 且 `max_drawdown ≤ 0.20` |
| medium | 3% | 預設 |
| low | 1% | 觀察期，新 wallet 強制 low 跑 30 天 |

**疊加規則**（同 token 多錢包觸發）：
- 同 symbol 已有部位 → **直接 skip**，不加碼
- 改用 `trust_total_score`：選最高 trust 那筆觸發

**Volatility 調整**：保留現有 `vol_adj`，但 cap 在 `[0.5, 1.5]`（避免極端低波幣種被無限放大）。

### Files
- `execution.py` `compute_position_size`: 加 `wallet: WalletScore` 參數
- 移除 `MAX_POSITION_PCT` 全域用法，改 `TRUST_POSITION_PCT_MAP`

### 測試
- `test_high_trust_wallet_gets_6pct_base`
- `test_low_trust_capped_at_1pct`
- `test_existing_position_skips_new_signal`
- `test_volatility_adjustment_capped`

---

## 🚨 TASK 6 — Wallet Refresh + Binance-Listable Filter

### 目標
1. 過去 180d 表現是後照鏡，每週重新評估
2. 撈出來的錢包必須交易**真的能在 Binance 跑的 token**

### 6a. 修改 `scripts/discover_wallets.py`
- 新增 CLI flag `--binance-listable-only`
- 撈完後 join 一份 `data/binance_symbols.json`（每日由 ccxt 自動更新）
- 過濾條件：wallet 過去 180d 在 Binance-listable token 的 PnL 必須 **≥ $30k** 才入庫
- 如果是 SOL 錢包但 80%+ 交易都是 Binance 沒上架的 meme → drop

### 6b. 新增 `scripts/refresh_wallets_weekly.py`
- 每週日 UTC 00:00 跑（用 cron 或 GitHub Actions）
- 流程：
  1. 從 Dune 撈最新 180d top wallets
  2. 對現有 active wallet 重新計算 30d performance
  3. 表現衰退（30d PnL < 0 或 win_rate < 0.45）→ 移到 `watch`
  4. `watch` 中連續 2 週仍差 → `retired`
  5. 新增前 50 名作為候選 `watch`
- **Telegram 推送變更摘要**：promoted X, demoted Y, retired Z

### Files
- `scripts/discover_wallets.py` (修改)
- `scripts/refresh_wallets_weekly.py` (新)
- `data/binance_symbols.json` (auto-generated)
- `wallet_scorer.py`: 加 `binance_listable_pnl_180d` 欄位

---

## 🚨 TASK 7 — 量化儀表（Daily Telegram Report）

### 目標
沒這些指標就無法迭代優化。

### 內容
每天 UTC 00:30 推送：
```
📊 Daily Report (2026-MM-DD)
━━━━━━━━━━━━━━━━━━━━━━━━
💰 Portfolio: $XX,XXX (Δ +X.XX% / 7d +XX.XX%)
📈 Realized PnL: $XXX (XX trades)
📉 Open positions: N (unrealized $XXX)

🎯 Hit rate: XX% (last 30 trades)
⚡ Avg mirror lag: XXs (p50) / XXs (p95)
💸 Avg cost per round-trip: XX bps

🏆 Top 3 wallets (30d PnL):
  1. 0xabc... +$XXX (X trades, win XX%)
  2. ...
🔻 Bottom 3 wallets (30d PnL):
  1. 0xdef... -$XXX → 建議 retire
  ...

🚦 Health: WS uptime XX%, LLM fallback rate X%, API rate-limit hits 0
```

### Files
- `reporting.py`: 新增 `build_daily_report(...)` → str
- `main.py`: `daily_summary_loop` 改用新格式
- `storage.py`: 新增 `TradesRepo.get_per_wallet_pnl(days)`、`get_mirror_lag_distribution(days)`

### 測試
- `test_daily_report_renders_correctly`
- `test_per_wallet_pnl_aggregation`

---

## 🚨 TASK 8 — Telegram 緊急控制

### 目標
人工介入機制，避免半夜爆單看不到。

### 指令
- `/pause`：停止所有新進場（保留 exit）
- `/resume`：恢復
- `/status`：當前部位 + 今日 PnL
- `/close <symbol>`：手動強制平倉
- `/closeall`：全平
- `/sl <symbol> <pct>`：手動調該 symbol 停損

**只接受 `TELEGRAM_CHAT_ID` 設定的 chat 發出的訊令**，其他人發來忽略。

### Files
- `reporting.py` `TelegramNotifier`: 加 `start_command_listener()` 用 `Application` + `CommandHandler`
- `main.py`: 啟動時 register 並 await application

### 測試
- `test_pause_blocks_new_entries`
- `test_unauthorized_chat_id_ignored`

---

## 🩺 TASK 9 — 反 MEV / 反 Wash Trade（Alpha 防偽）

### 目標
鏈上很多「smart money」其實是 MEV bot / sandwich attacker，**他們的進出場對你毫無 alpha**。

### 偵測規則
標記為 `is_mev_suspect` 並降級 trust 一階：
1. **Same-block in-out**：同 wallet 同 token 在同一個 block 內 swap_in + swap_out
2. **High trade frequency**：24h 內 >100 次 swap
3. **Mirror trades to known MEV bots**：維護 `data/mev_blacklist.json`（社群有公開列表，例：jaredfromsubway.eth 各鏈分身）

### Files
- `signals/mev_detector.py` (新)
- `monitors.py`: 每個 event 過 `mev_detector.check()`
- `wallet_scorer.py`: 收到 `is_mev_suspect` 連續 3 次 → auto retire

---

## 🩺 TASK 9b — MEV Blacklist 自動更新腳本（每月 cron）

### 目標
取代手動維護 `data/mev_blacklist.json`。每月跑一次，從外部資料源拉新 MEV bot，merge 進現有檔案，**只增不刪**（避免誤殺已驗證條目）。

### 資料源優先序

#### Primary: Dune SQL（user 已安裝 `dune` CLI，最可靠）
跑兩個 query：

**Query A — ETH sandwich attackers（過去 30 天）：**
```sql
SELECT
    LOWER(CAST(searcher_eoa AS VARCHAR)) AS address,
    SUM(profit_usd) AS profit_30d,
    COUNT(*) AS sandwich_count
FROM mev.sandwich_aggregated_summary
WHERE block_date >= CURRENT_DATE - INTERVAL '30' DAY
    AND blockchain = 'ethereum'
    AND profit_usd > 0
GROUP BY searcher_eoa
HAVING SUM(profit_usd) >= 5000 AND COUNT(*) >= 20
ORDER BY profit_30d DESC
LIMIT 100
```
產出：地址 + 過去 30d sandwich 獲利 + 次數。**這是最可靠的單一來源。**

**Query B — 高頻 EOA（被動偵測 arbitrage bot）：**
```sql
SELECT
    LOWER(CAST(taker AS VARCHAR)) AS address,
    COUNT(*) AS trades_30d,
    COUNT(DISTINCT token_bought_address) AS token_diversity,
    COUNT(DISTINCT block_number) AS unique_blocks
FROM dex.trades
WHERE block_date >= CURRENT_DATE - INTERVAL '30' DAY
    AND blockchain = 'ethereum'
GROUP BY taker
HAVING COUNT(*) >= 3000
    AND COUNT(*) * 1.0 / COUNT(DISTINCT block_number) >= 0.8  -- 多筆同 block
ORDER BY trades_30d DESC
LIMIT 50
```
產出：高頻交易地址（疑似 arbitrage bot）。**標 confidence=medium，category=arbitrage。**

#### Secondary fallback: libmev.com 公開 leaderboard
若 Dune CLI 失敗（auth expired / quota），fallback 抓：
```
GET https://api.libmev.com/v1/bundles/leaderboard?timeframe=month&limit=100
```
回傳 JSON 含 `searcher_address` + `profit`。**標 confidence=medium。**

#### Tertiary: 不嘗試 EigenPhi（需付費）

### 執行流程
```
1. Load existing data/mev_blacklist.json
2. 用 dune CLI 跑 Query A → 取得新 ETH sandwich 地址清單
3. 用 dune CLI 跑 Query B → 取得新 ETH high-freq 地址清單
4. 若 Dune 失敗 → fallback libmev API
5. Merge：
   - 已存在地址 → 更新 metadata（profit_30d、last_seen_utc）
   - 不存在地址 → 新增條目（confidence 依來源決定）
6. 不刪除任何現有條目（避免誤殺）
7. 對比 active wallets：若任何 active wallet 出現在新 blacklist → 立刻 Telegram 高優先警告 +
   寫入 data/wallet_decisions.jsonl 標記為 retire
8. Telegram 推送摘要：
   "🛡️ MEV Blacklist Refresh
    Added: N new bots (ETH X, BSC Y, SOL Z)
    Updated: M existing entries
    ⚠️ ALERT: K of your active wallets matched and were auto-retired"
```

### Schema 規則
新增條目格式必須與 `data/mev_blacklist.json` 完全一致：
```json
{
  "address": "0x... (lowercase) or base58",
  "label": "Auto-detected MEV (Dune sandwich, $XXX 30d profit)",
  "category": "sandwich" | "arbitrage" | "unknown_mev",
  "confidence": "high" | "medium" | "low",
  "source": "dune.mev.sandwich_aggregated_summary" | "dune.dex.trades.high_freq" | "libmev.api.leaderboard",
  "first_seen_utc": "2026-MM-DD",
  "last_seen_utc": "2026-MM-DD",
  "profit_usd_30d": 12345.67  // optional, 只有 sandwich 來源有
}
```

**Confidence 賦值規則：**
- Query A (sandwich, profit ≥ $20k) → `high`
- Query A (sandwich, $5k–$20k) → `medium`
- Query B (high-freq) → `medium`
- libmev fallback → `medium`
- 任何來源 profit < $5k 或 trades < 20 → 不收

### Files
- `scripts/refresh_mev_blacklist.py` (新)
- `scripts/sql/mev_sandwich_eth_30d.sql` (新, Query A)
- `scripts/sql/mev_highfreq_eth_30d.sql` (新, Query B)

### 排程
**不寫進專案內的 scheduler**——避免 Zeabur 容器掛掉漏跑。改用以下兩種之一（在 README 註明）：

**選項 1：本機 cron（macOS launchd / Linux crontab）**
```cron
# 每月 1 號 UTC 02:00 跑
0 2 1 * * cd /path/to/crypto_copy_trader && .venv/bin/python scripts/refresh_mev_blacklist.py >> data/mev_refresh.log 2>&1
```

**選項 2：GitHub Actions（推薦，免維護）**
```yaml
# .github/workflows/refresh_mev_blacklist.yml
on:
  schedule:
    - cron: '0 2 1 * *'  # 每月 1 號 UTC 02:00
  workflow_dispatch:      # 也允許手動觸發
jobs:
  refresh:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
      - run: pip install -r requirements.txt
      - run: python scripts/refresh_mev_blacklist.py
        env:
          DUNE_API_KEY: ${{ secrets.DUNE_API_KEY }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
      - run: |
          if [[ -n $(git status -s) ]]; then
            git config user.name "mev-bot-refresh"
            git config user.email "noreply@github.com"
            git add data/mev_blacklist.json
            git commit -m "chore: auto-refresh MEV blacklist $(date -u +%Y-%m-%d)"
            git push
          fi
```
**注意**：GitHub Actions 方案會自動 commit 到 main，部署平台（Zeabur）會自動 redeploy 拉到最新 blacklist。

### 邊界情況
1. **Dune CLI 未安裝或 auth 失效**：fallback 到 libmev，**不要直接 fail**，發 Telegram 警告
2. **libmev API 也掛掉**：log 並退出 0（exit 0）—不要讓 cron 一直 retry 累積錯誤
3. **JSON 寫入失敗**：先寫 `data/mev_blacklist.json.tmp` → 驗證能 `json.load` → atomic rename，避免半寫狀態破壞檔案
4. **新增條目超過 200 筆**：很可能 query 出錯（資料源異常），refuse to write，發警告人工檢視
5. **`_meta` 區塊**：保留並更新 `last_updated_utc`，不要被 merge 邏輯覆蓋

### 環境變數新增（要 append 到 .env）
```bash
# Task 9b: MEV Blacklist Refresh
DUNE_API_KEY=                              # dune.com/settings/api 取得
MEV_REFRESH_LIBMEV_API_URL=https://api.libmev.com/v1/bundles/leaderboard
MEV_REFRESH_MIN_PROFIT_USD=5000            # 收錄門檻
MEV_REFRESH_MAX_NEW_ENTRIES=200            # 安全護欄
MEV_REFRESH_LOG_PATH=data/mev_refresh.log
```

### 測試
- `test_merge_preserves_existing_entries`
- `test_merge_does_not_overwrite_high_confidence_with_medium`
- `test_dune_failure_falls_back_to_libmev`
- `test_active_wallet_match_triggers_telegram_alert`
- `test_atomic_write_prevents_corruption`
- `test_max_new_entries_safety_guard`

### 驗收
- 第一次手動跑 `python scripts/refresh_mev_blacklist.py`：應在 60 秒內完成，產出更新後的 blacklist + Telegram 摘要訊息
- 連跑兩次：第二次應該 `Added: 0 new bots, Updated: N existing entries`（idempotent）
- 模擬 Dune fail：應 fallback libmev 並完成
- 模擬 libmev 也 fail：應 exit 0 並 Telegram 警告，**不破壞現有 blacklist**

---

## 🧯 TASK 10 — 故障容錯

### 必做
1. **Crash mid-execute**：下單後寫 `data/pending_orders.jsonl`，restart 時對賬 Binance `fetch_open_orders` 與檔案，補齊 `PositionsRepo`
2. **時區**：daily_pnl_circuit reset 用 UTC 不用 local time
3. **Decimal 一致性**：所有金額用 `Decimal`，禁止 `float`（看到 `compute_position_size` 用 `float()` 轉 vol，這裡會累積誤差）
4. **Binance API key 權限驗證**：啟動時呼叫 `fetch_balance` 確認 spot 權限存在、`fetch_my_trades` 確認讀取權限、**禁止 withdraw 權限存在時繼續**（防被盜）

### Files
- `main.py`: `_validate_api_permissions(executor)` 啟動 sanity check
- `storage.py`: `PendingOrdersRepo`
- `execution.py`: 替換所有 `float` for money

---

## 📋 你（user）需要先準備

Codex 開工前，請先在專案根目錄放：
1. `data/binance_symbols.json` — 跑 `python -c "import ccxt; print([s for s in ccxt.binance().load_markets() if s.endswith('/USDT')])"` 存進去
2. `data/known_token_map.json` — 至少 100 個常見 token 的 `(chain, address) → binance_symbol` 對應（可用社群 list：CoinGecko id → contract → binance ticker）
3. `data/mev_blacklist.json` — 從 https://github.com/flashbots/mev-inspect-py 或 Etherscan 「MEV bot」標籤錢包整理
4. 在 `.env` 補：
   - `ALCHEMY_ETH_WSS_URL`（免費註冊）
   - `MAKER_ORDER_TIMEOUT_SECONDS=1.5`
   - `STOP_LOSS_PCT=-0.08`
   - `TRAILING_STOP_DRAWDOWN_PCT=0.30`
   - `TRAILING_STOP_TRIGGER_PCT=0.20`
   - `TIME_STOP_HOURS=48`
   - `MAX_HOLD_HOURS=168`

---

## 🎯 實作順序與預估時間

| 順序 | Task | 預估工時 | 預期 PnL 改善 |
|------|------|----------|---------------|
| 1 | Task 1 (Mirror Exit) + Task 2 (Stop Loss) | 2 天 | **+15~25%** |
| 2 | Task 10 (容錯) + 全域前置條件 A/B/C/D | 1.5 天 | 防止崩潰歸零 |
| 3 | Task 3 (Latency) + Task 8 (Telegram 控制) | 1.5 天 | **+5~10%** |
| 4 | Task 4 (Maker Order) + Task 5 (Sizing) | 1 天 | **+3~5%** |
| 5 | Task 7 (Daily Report) | 0.5 天 | 量化基礎 |
| 6 | Task 6 (Wallet Refresh) + Task 9 (MEV filter) | 1.5 天 | **+5~10% 長期** |
| 7 | Task 9b (MEV Blacklist auto-refresh) | 0.5 天 | 0 維護成本 |

總計約 **8.5 個工作天**。每個 Task 完成後跑完整 test suite（≥80% coverage）才合併。

---

## 🚫 禁止事項（給 Codex）
1. **禁止關閉 paper_trading 模式**——所有開發都在 `PAPER_TRADING=true` 完成，user 親自切到 live
2. **禁止寫 try/except 吞錯誤**——除非是已知 transient（參考現有 `BUG-8` 修復原則）
3. **禁止用 float 處理金額**——一律 `Decimal`
4. **禁止跳過寫測試**——每個新邏輯先 RED → GREEN → REFACTOR
5. **禁止改動 `.env.example` 後不更新 README**
6. **禁止刪除現有 BUG-1 ~ BUG-12 的 regression tests**

---

## ✅ 驗收標準（整體）
- 全部 Task 完成後跑 `pytest --cov=. --cov-report=term-missing`，覆蓋率 ≥ 80%
- 在 `PAPER_TRADING=true` 下連跑 7 天，產出 daily report，**未發生**：
  - 任何 unhandled exception
  - 任何「下單成功但 PositionsRepo 沒記錄」的對賬錯誤
  - 任何 Binance API rate-limit error
- 7 天 paper trading 結算：mirror lag p50 < 30s、avg cost per round-trip < 30 bps
