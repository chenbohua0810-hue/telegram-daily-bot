# Crypto Copy Trader — 現況總結

> 最後更新：2026-04-25（paper trading 已可啟動，SOL 監控需 Pro key）

---

## 已完成

### 程式碼與測試
- 209 個測試通過，1 個已知失敗（`test_missing_required_env_raises`，worktree fixture 問題，不影響主線）
- BUG-1：`execution.py` retry 未捕捉 `ccxt.NetworkError` → 已修復
- BUG-2：`WalletScorer` 繞過 `AddressesRepo` 直接存取私有屬性 → 已修復
- BUG-3：`_count_consecutive_losses` 把 ROI=None 算成獲利 → 已修復
- BUG-4：`realized_slippage_pct` 只計算 `paper` 不計 `filled` → 已修復
- BUG-5：`fetch_history_sol_birdeye` 用 `quote_value - base_value` 計算 PnL（AMM swap 永遠≈0）→ 已修復（改用活躍度指標）

### 功能模組
- P0/P1/P2/P3 優先路由（`signals/router.py`）
- Anthropic / OpenAI-compatible / Fallback 後端
- BatchScorer：window flush / max batch flush / token overflow split
- WebSocket monitor：reconnect backoff / heartbeat timeout / gap backfill
- Runtime health 指標：`backend_fallback_rate` / `batch_flush_latency_ms` / `ws_reconnect_count`

### 錢包 Pipeline（已完成）

**`scripts/discover_wallets.py`** — Stage-1 候選發現
- `--source birdeye-sol`：Birdeye 1W top traders（offset=0，第一頁）
- **`--source birdeye-sol-active`**（新）：Birdeye 1W top traders offset=10（第二頁），找到更多活躍投機者
  - 9 個 pytest 案例全通過（`tests/test_discover_enrich.py`）
- **`enrich_birdeye_sol_diversity`**：discover 階段過濾 LST-only 錢包（7d 取樣窗口）
  - `lst_swap_ratio > 0.70` → SKIP
  - `--skip-enrich` flag 可關閉（debug/replay 用）
- `--source all`：GMGN → Birdeye page1 → Birdeye page2（依序 fallback）
- `--source dune-csv-eth`：Dune 手動匯出 CSV
- `--source gmgn-sol`：GMGN 30d rank（Cloudflare 保護，403 時自動 fallback）

**`scripts/promote_wallets.py`** — Stage-2 晉升評估
- GMGN 403 時自動 fallback 到 Birdeye `trader/txs/seek_by_time`
- **Birdeye fallback 改用活躍度晉升**（`gmgn_verified=False` 路徑）：
  - AMM swap tx 無法計算 realized PnL → 改判斷 `trade_count ≥ 50 AND diversity ≥ 8 AND last_trade ≤ 30d`
  - 保留 GMGN 驗證路徑的完整 PnL/Sharpe 邏輯不變
- 純函式架構：`compute_sharpe_like` / `compute_max_drawdown_ratio` / `detect_sybil_clusters` / `decide`

**`monitors.py`** — SOL Monitor
- SolMonitor：401/403 時 graceful 跳過（記錄警告，回傳空 events，不 crash）

### 環境設定（`.env`）
| 金鑰 | 狀態 |
|------|------|
| BINANCE_API_KEY / SECRET | ✅ 已填 |
| ANTHROPIC_API_KEY | ✅ 已填 |
| LLM_PRIMARY_API_KEY (Groq) | ✅ 已填 |
| ETHERSCAN_API_KEY | ✅ 已填 |
| SOLSCAN_API_KEY | ⚠ 已填但為 free key（pro-api 需付費，SOL 監控會回傳空） |
| TELEGRAM_BOT_TOKEN / CHAT_ID | ✅ 已填 |
| BIRDEYE_API_KEY | ✅ 已填（免費 tier，limit ≤ 10） |
| USE_WEBSOCKET | ✅ 已設 false（REST polling 模式，無需 WSS URL） |
| BSCSCAN_API_KEY | ⬜ 選填（BSC monitor 已停用） |
| CRYPTOPANIC_API_KEY | ⬜ 選填（無 key 自動略過） |

### 目前 Active 錢包
| 地址 | 鏈 | 特性 |
|------|-----|------|
| `6i1ySwePEKUfE9Bs...` | SOL | 61 交易，diversity=15，stablecoin arb（USDT↔USDC） |
| `973vghafz4fQYB3M...` | SOL | 118 交易，diversity=21，meme coin 交易（SpaceX/xAI/GENIUS vs SOL） |

---

## 驗收清單

- [x] `discover_wallets.py` 成功寫入 ≥1 筆 watch 錢包
- [x] `promote_wallets.py` 成功評估並晉升 ≥1 筆為 active（2 筆：activity-based）
- [x] 啟動後無立即 crash（SOL API 401 graceful 處理）
- [ ] Telegram 收到「crypto copy trader started」通知 ← 需手動確認
- [ ] `data/events.jsonl` 至少寫入 1 筆事件 ← 需 SOL Pro key 或 Birdeye monitor

---

## 已知限制

| 問題 | 原因 | 狀態 |
|------|------|------|
| GMGN 403 | Cloudflare 保護，需瀏覽器 session/cookie | 已有 Birdeye fallback |
| Birdeye gainers PnL ≠ realized PnL | AMM swap 兩側永遠等值，歷史成本在 30d 窗口外 | 改用活躍度晉升路徑 |
| Birdeye 免費 tier limit ≤ 10 | 超過 10 筆返回 400 | discover 已限制 `--limit 10` |
| Solscan pro-api 401 | SOLSCAN_API_KEY 為免費 key，pro-api 需付費 | graceful skip，SOL 無法監控新 tx |
| `6i1ySwePEK` 為 stablecoin arb | USDT↔USDC 微利，幾乎不值得複製 | 長期觀察後可手動 retire |

---

## 下一步

### 解除 SOL 監控封鎖（選一）

**選項 1（最快）**：升級 Solscan Pro key（$99/月）
```
SOLSCAN_API_KEY=<pro_key>
```

**選項 2（免費）**：改用 Helius SOL API（需在 helius.dev 申請免費 key）
- 需要修改 `SolMonitor._base_url` 和 `_request_transfers`

**選項 3（已有 key）**：用 Birdeye 做 SOL monitoring
- 用 `trader/txs/seek_by_time` 輪詢新 tx
- 需新增 `BirdeyeSolMonitor` class（約 80 行）

### 啟動 paper trading
```bash
cd crypto_copy_trader
export $(grep -v '^#' .env | grep -v '^$' | xargs)
.venv/bin/python main.py
```

### 補充更好的 SOL 錢包
```bash
# 再跑一次 discover 換更多候選（偏移量 20 以上）
.venv/bin/python scripts/discover_wallets.py --source birdeye-sol-active --limit 10
# 或手動加入已知的 SOL meme coin KOL 地址
```

---

## 之後可選做

- 補 BSC 支援（`discover` / `promote` 都有 TODO stub）
- 補 WebSocket providers（`ETH_WSS_URL` / `SOL_WSS_URL`）降低 polling 延遲
- `PAPER_TRADING=false` 切 live 前，先 paper 模式觀察至少 3 天

---

## 詳細操作步驟

參見 `docs/runtime-runbook.md`
