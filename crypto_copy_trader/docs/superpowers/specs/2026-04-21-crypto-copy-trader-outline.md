# Crypto Copy Trader — 文字大綱

---

## 1. 專案定位

追蹤鏈上高勝率、大資金地址的操作，在 Binance 執行對應跟單。鏈上只做信號偵測，不直接上鏈交易。

---

## 2. 四層架構

- **Layer 1 — 鏈上偵測**：EthMonitor / SolanaMonitor / BSCMonitor 輪詢各鏈 API，偵測追蹤地址的新交易
- **Layer 2 — 信號處理**：QuantFilter 先過濾（交易金額、幣種是否上 Binance）→ AIScorer（Claude Haiku 評信心分）→ SlippageFeeEstimator（成本預估，超標就丟棄）
- **Layer 3 — 執行**：PositionSizer（固定 % 倉位）→ BinanceExecutor（ccxt 下單）→ RiskGuard（每日熔斷、曝險上限）
- **Layer 4 — 分析與通知**：TradeLogger → PerformanceTracker（量化歷史跟單績效）→ TelegramNotifier

---

## 3. 地址管理

- 來源：Nansen / Arkham API 取標籤地址
- 篩選門檻：勝率 ≥ 55%、資金 ≥ $100K、交易 ≥ 20 筆、持倉 1h–30天、最大回撤 ≤ 40%
- 每週重新評估，自動淘汰衰退地址

---

## 4. 滑價 & 手續費

- 小單（< $10K）固定 0.1% 滑價；中大單查 order book 估算
- Binance 手續費來回 0.2%（BNB 折扣後 0.15%）
- 若總成本 > 預期報酬 × 30%，直接放棄該信號

---

## 5. 風險控制

- 單幣曝險上限 10%
- 每日虧損 -5% 觸發熔斷
- 最多同時 10 個持倉
- 預設 paper trading 模式

---

## 6. 資料儲存

- `addresses.db`：地址評分與歷史績效（SQLite）
- `trades.db`：跟單紀錄與損益（SQLite）
- `events.jsonl`：鏈上事件原始 log

---

## 7. v1 不做

DEX 直接上鏈、WebSocket 即時監聽、做空/衍生品、Web Dashboard
