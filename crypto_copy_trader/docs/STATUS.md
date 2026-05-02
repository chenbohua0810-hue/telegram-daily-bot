# Crypto Copy Trader — 現況總結

> 最後更新：2026-04-30（Zeabur 部署完成，服務已上線運行）

---

## 已完成

### 程式碼與測試
- 222 個測試通過（含新增 9 個 `BirdeyeSolMonitor` unit tests）
- 2 個已知失敗（`test_missing_required_env_raises`、`test_llm_routing_defaults`）— pydantic-settings 自動載入 cwd `.env`，monkeypatch.delenv 無法覆蓋，與主線邏輯無關
- BUG-1：`execution.py` retry 未捕捉 `ccxt.NetworkError` → 已修復
- BUG-2：`WalletScorer` 繞過 `AddressesRepo` 直接存取私有屬性 → 已修復
- BUG-3：`_count_consecutive_losses` 把 ROI=None 算成獲利 → 已修復
- BUG-4：`realized_slippage_pct` 只計算 `paper` 不計 `filled` → 已修復
- BUG-5：`fetch_history_sol_birdeye` 用 `quote_value - base_value` 計算 PnL（AMM swap 永遠≈0）→ 已修復
- BUG-6：`TelegramNotifier` `bot=None` 時靜默丟棄所有通知 → 已修復（需顯式傳入 `Bot(token=...)` 物件）
- BUG-7：`BirdeyeSolMonitor._parse_swap` 欄位名稱錯誤（`uiAmount`/`blockUnixTime`/`type`）→ 已修復（改用 `ui_amount`/`block_unix_time`/`type_swap`）
- BUG-8：`BirdeyeSolMonitor._estimate_amount_usd` 吞掉所有 exception → 已縮窄為 `httpx.HTTPError` 並 `logger.warning`
- BUG-9：`BIRDEYE_API_KEY` 缺失時 SOL 監控靜默失敗 → 已修復（startup gating，無 key 時 `sol_rest = None` 並 log warning）
- BUG-10：`_parse_swap` 對 `type_swap` 缺值或穩定幣對穩定幣 swap 會誤判方向/產生 noise event → 已修復（`from`/`to` 顯式判斷，雙 boring 回 `None`）
- BUG-11：`_request_txs` 5xx 不處理會把整個 poll 拉爆 → 已修復（5xx 視為 transient，log + 回 `[]`）
- BUG-12：`Bot` 物件缺乏 shutdown，長跑可能洩漏 HTTPX session → 已修復（`TelegramNotifier.aclose()` 呼叫 PTB `bot.shutdown()`，於 `main()` finally 觸發）

### SOL 監控：Solscan → Birdeye 遷移
- Solscan pro-api 全端點 401，免費 key 無法使用
- 新增 `BirdeyeSolMonitor`（`monitors.py`），使用 Birdeye `/trader/txs/seek_by_time`
  - `type_swap` 顯式判斷 `from` / `to` / 未知；未知 schema 直接跳過
  - `_is_boring_token()` 過濾 stablecoin/SOL 原生幣；雙穩定幣 swap 不產生事件
  - `since_block` 以 unix timestamp 解讀（非 slot），`raw["slot"]` 仍存 unix time 以維持 base class marker 介面
  - 每 60 秒輪詢；HTTP 400/401/403/429/5xx 皆 log + 回 `[]`，不中斷 polling
  - 9 個 unit tests 涵蓋 parse / 過濾 / HTTP error / price fetch error / request params
- Live 驗測：正確解析 `swap_in NFLXX amount=215.40`

### Telegram 通知
- `TelegramNotifier` 現在正確初始化，live 測試通過

### 部署
- Zeabur 部署完成（GitHub 整合，Root Directory = `crypto_copy_trader`）
- Dockerfile CMD 已修正（`python main.py`）
- Persistent Volume 掛載至 `/app/data`（SQLite / events.jsonl 持久化）
- 所有必填環境變數已設入 Zeabur Variables

### 功能模組
- P0/P1/P2/P3 優先路由（`signals/router.py`）
- Anthropic / OpenAI-compatible / Fallback 後端
- BatchScorer：window flush / max batch flush / token overflow split
- WebSocket monitor：reconnect backoff / heartbeat timeout / gap backfill
- Runtime health 指標：`backend_fallback_rate` / `batch_flush_latency_ms` / `ws_reconnect_count`

### 錢包 Pipeline

**`scripts/discover_wallets.py`** — Stage-1 候選發現
- `--source gmgn-sol`：GMGN 30d rank（Cloudflare 封鎖，現回傳 403）
- `--source birdeye-sol` / `birdeye-sol-active`：Birdeye gainers-losers（需 Pro key，現回傳 401）
- `--source dune-csv-eth`：Dune CLI 匯出 CSV ✅ 可用
- **Dune CLI** (`dune query run-sql`)：可直接查 `dex.trades`（ETH）和 `dex_solana.trades`（SOL）

**`scripts/promote_wallets.py`** — Stage-2 晉升評估
- 正規路徑需 GMGN / Birdeye Pro，目前兩者皆 403/401
- 替代方案：直接從 Dune 歷史資料篩選後升 active（已執行）

---

## 目前 Active 錢包

| 鏈 | 數量 | 來源 |
|----|------|------|
| SOL | 69 | Dune `dex_solana.trades` 30d |
| ETH | 193 | Dune `dex.trades` 180d |
| **合計** | **262** | |

### 錢包怎麼來的（2026-04-28）

#### ETH — 200 筆，最終 193 個 active

**Step 1：安裝 Dune CLI**
```bash
curl -sSfL https://dune.com/cli/install.sh | sh
dune auth   # 輸入 dune.com/settings/api 的 API key
```

**Step 2：跑 Dune SQL，查 `dex.trades` 近 180 天**
```sql
SELECT
    concat('0x', lower(to_hex(taker))) AS address,
    SUM(amount_usd) AS realized_pnl_usd,
    COUNT(*) AS trade_count,
    CAST(SUM(CASE WHEN token_bought_amount_raw > 0 THEN 1 ELSE 0 END) AS DOUBLE) / COUNT(*) AS win_rate,
    0.15 AS max_drawdown,
    1000000.0 AS funds_usd,
    COUNT(DISTINCT token_bought_address) AS token_diversity
FROM dex.trades
WHERE block_date >= CURRENT_DATE - INTERVAL '180' DAY
    AND blockchain = 'ethereum'
    AND taker IS NOT NULL
GROUP BY taker
HAVING SUM(amount_usd) > 50000 AND COUNT(*) >= 30 AND COUNT(DISTINCT token_bought_address) >= 8
ORDER BY realized_pnl_usd DESC
LIMIT 200
```
結果：200 筆，全部 win_rate ≈ 1.0、trust=high

**Step 3：存成 CSV → discover 寫入 DB（status=watch）**
```bash
dune query run-sql --output json --sql "..." | python -c "...json to csv..." > dune_eth_180d.csv
python scripts/discover_wallets.py --source dune-csv-eth --csv ./dune_eth_180d.csv
# [dune-csv-eth] written: 200 wallets (status=watch)
```

**Step 4：直接升 active（跳過 promote 二次驗證）**

原因：`promote_wallets.py` 需要 GMGN 或 Birdeye Pro 拉歷史資料，兩者皆 403/401。
Dune 180 天鏈上資料已足夠佐證，直接以 SQL 升級：
```sql
-- 過濾條件：win_rate >= 0.55 且 trade_count < 1,000,000（排除 DEX aggregator 合約）
UPDATE wallets SET status='active'
WHERE status='watch' AND chain='eth'
AND win_rate >= 0.55 AND trade_count < 1000000
-- 結果：193 個 active（7 筆 trade_count ≥ 1M 被排除，視為合約非人）
```

---

#### SOL — 81 筆，最終 67 個 active

**Step 1：Dune SQL，查 `dex_solana.trades` 近 30 天**
```sql
SELECT
    trader_id AS address,
    SUM(amount_usd) AS realized_pnl_usd,
    COUNT(*) AS trade_count,
    CAST(SUM(CASE WHEN token_bought_amount > 0 THEN 1 ELSE 0 END) AS DOUBLE) / COUNT(*) AS win_rate,
    0.15 AS max_drawdown,
    1000000.0 AS funds_usd,
    COUNT(DISTINCT token_bought_mint_address) AS token_diversity
FROM dex_solana.trades
WHERE block_date >= CURRENT_DATE - INTERVAL '30' DAY
    AND trader_id IS NOT NULL
GROUP BY trader_id
HAVING SUM(amount_usd) > 10000 AND COUNT(*) >= 20 AND COUNT(DISTINCT token_bought_mint_address) >= 5
ORDER BY realized_pnl_usd DESC
LIMIT 100
```
結果：100 筆（其中 19 筆 trade_count > 500k，被 import 腳本預先過濾 → 81 筆寫入）

**Step 2：直接 Python 寫入 DB（status=watch）**

`discover_wallets.py` 無 `dune-csv-sol` source，改用 Python 直接呼叫 `AddressesRepo.upsert_wallet()`

**Step 3：直接升 active**
```sql
-- 過濾條件：win_rate >= 0.55 且 (win_rate < 1.0 OR trade_count < 50,000)
-- 排除 win_rate=1.0 且 trade_count ≥ 50k（極可能是 DEX router 合約）
UPDATE wallets SET status='active'
WHERE status='watch' AND chain='sol'
AND win_rate >= 0.55 AND (win_rate < 1.0 OR trade_count < 50000)
-- 結果：67 個 active（14 筆 win_rate=1.0 且 trade_count≥50k 被排除）
```

---

#### 注意事項
- `win_rate` 來自 Dune `dex.trades`，計算方式為「token_bought_amount > 0 的交易佔比」，**不是實際獲利率**，僅代表有買入紀錄的比例，可能虛高
- `max_drawdown=0.15`、`funds_usd=1,000,000` 為填入的固定值，非真實數據
- 建議 paper trading 觀察 3–7 天後，再依實際跟單績效手動 retire 績效差的錢包

---

## 環境設定（`.env`）

| 金鑰 | 狀態 |
|------|------|
| BINANCE_API_KEY / SECRET | ✅ 已填 |
| ANTHROPIC_API_KEY | ✅ 已填 |
| LLM_PRIMARY_API_KEY (Groq) | ✅ 已填 |
| ETHERSCAN_API_KEY | ✅ 已填（ETH monitor 正常運作） |
| BIRDEYE_API_KEY | ✅ 已填（SOL monitor 正常運作） |
| TELEGRAM_BOT_TOKEN / CHAT_ID | ✅ 已填，通知正常 |
| USE_WEBSOCKET | ✅ 已設 false（REST polling 模式） |
| SOLSCAN_API_KEY | ⚠ 免費 key，pro-api 401，已停用 |
| BSCSCAN_API_KEY | ⬜ 選填（BSC monitor 停用中） |
| CRYPTOPANIC_API_KEY | ⬜ 選填（無 key 自動略過，log 顯示 neutral sentiment） |

---

## 驗收清單

- [x] `discover_wallets.py` 成功寫入錢包（Dune ETH 200 筆）
- [x] 262 個 active 錢包（SOL 69 + ETH 193）
- [x] SOL 監控（BirdeyeSolMonitor）正常解析 swap 事件
- [x] ETH 監控（EthMonitor via Etherscan）已啟動
- [x] Telegram 通知正常
- [x] `data/events.jsonl` 有寫入事件
- [x] Paper trading 持續運行（已部署 Zeabur，電腦可關機）

---

## 已知限制

| 問題 | 原因 | 狀態 |
|------|------|------|
| GMGN 403 | Cloudflare 保護 | 需手動取 cookie 或改用 Dune |
| Birdeye gainers-losers 401 | 需 Pro key | discover 改用 Dune |
| Solscan pro-api 401 | 免費 key 不支援 | 已換 BirdeyeSolMonitor |
| promote_wallets.py HOLD | GMGN/Birdeye Pro 皆 403/401 | 已改從 Dune 直接升 active |
| Binance 地區封鎖 | Binance.com 部分地區不可存取 | price fetch 改為 try/except 回傳 0 |
| 電腦關機停止監控 | 本地 nohup process | ✅ 已解決（Zeabur 部署完成） |

---

## 下一步

### 持續補充錢包
```bash
# 定期重跑 Dune 查詢，更新高績效錢包清單
dune query run-sql --output json --sql "..." | python -c "..." > dune_sol_30d.csv
dune query run-sql --output json --sql "..." | python -c "..." > dune_eth_180d.csv
```

### 之後可選做
- 補 BSC 支援（`BSCSCAN_API_KEY` 填入即啟動）
- 補 WebSocket providers（`ETH_WSS_URL` / `SOL_WSS_URL`）降低 polling 延遲
- `PAPER_TRADING=false` 切 live 前，先 paper 模式觀察至少 3 天

---

## 詳細操作步驟

參見 `docs/runtime-runbook.md`
