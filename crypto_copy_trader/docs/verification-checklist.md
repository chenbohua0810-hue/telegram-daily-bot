# Verification Checklist

## Automated

- [x] `pytest` 全綠
- [x] `pytest --cov` 覆蓋率 ≥ 80%
- [x] LLM routing 已完成：PriorityRouter / AnthropicBackend / OpenAICompatBackend / FallbackBackend
- [x] Batch scorer 已完成：window flush / size flush / token overflow split / future error propagation
- [x] runtime pipeline 已完成 P0 / P1 / P2 / P3 路由整合
- [x] WebSocket monitor 已完成 reconnect / heartbeat timeout / gap backfill 測試
- [x] runtime health 已補 `backend_fallback_rate` / `batch_flush_latency_ms` / `ws_reconnect_count`
- [x] 離線整合測試已覆蓋「通過全部 filter 的事件會產生 `status='paper'` trade 並正確回填 `decision_snapshots.trade_id`」
- [x] 離線整合測試已覆蓋「被 quant filter 擋下的事件會產生 `final_action='skip'`、skip snapshot 會完整保留」
- [x] 離線 wallet scorer 測試已覆蓋 `addresses.db` history 會寫入紀錄

目前本 worktree 本地驗證結果：
- `200 passed`
- coverage `92.56%`

## Runtime Acceptance

- [ ] `python -m crypto_copy_trader.main` 在 paper trading 模式下可啟動、連續跑 1 小時無 crash
- [ ] Telegram 收到啟動通知
- [ ] `data/events.jsonl` 有至少 1 筆事件寫入
- [ ] 切換 `PAPER_TRADING=false` 前，仍需在真實環境手動跑一次 wallet scorer，確認 `addresses.db` 有 history 紀錄
- [x] 已提供 `python -m verification.runtime_health --hours 24` 作為 runtime artifact summary 指令

## 24h Paper Trading SQL Health Checks

- [x] 已提供 `python -m verification.runtime_health --hours 24` 彙整上述三項查詢
- [ ] 在真實 paper trading 跑滿 24 小時後，執行 `python -m verification.runtime_health --hours 24`
