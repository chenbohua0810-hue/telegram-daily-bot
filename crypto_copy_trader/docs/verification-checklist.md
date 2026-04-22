# Verification Checklist

## Automated

- [x] `pytest` 全綠
- [x] `pytest --cov` 覆蓋率 ≥ 80%
- [x] 離線整合測試已覆蓋「通過全部 filter 的事件會產生 `status='paper'` trade 並正確回填 `decision_snapshots.trade_id`」
- [x] 離線整合測試已覆蓋「被 quant filter 擋下的事件會產生 `final_action='skip'`、`skip_reason='below_min_trade_usd'`，且 technical / sentiment / ai / risk / cost 皆為 `NULL`」
- [x] 離線 wallet scorer 測試已覆蓋 `addresses.db` history 會寫入紀錄

## Runtime Acceptance

- [ ] `python -m crypto_copy_trader.main` 在 paper trading 模式下可啟動、連續跑 1 小時無 crash
- [ ] Telegram 收到啟動通知
- [ ] `data/events.jsonl` 有至少 1 筆事件寫入
- [ ] 切換 `PAPER_TRADING=false` 前，仍需在真實環境手動跑一次 wallet scorer，確認 `addresses.db` 有 history 紀錄

## 24h Paper Trading SQL Health Checks

- [ ] `SELECT final_action, COUNT(*) FROM decision_snapshots GROUP BY final_action;`
- [ ] `SELECT skip_reason, COUNT(*) FROM decision_snapshots WHERE final_action='skip' GROUP BY skip_reason;`
- [ ] `SELECT AVG(realized_slippage_pct), AVG(estimated_slippage_pct) FROM trades WHERE status='paper';`
