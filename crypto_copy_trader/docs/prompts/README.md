# Wallet Pipeline Prompts

這個資料夾存放「錢包發現 → 晉升 → 持續評估」三階段 pipeline 的 Sonnet 任務 prompt。
每個 prompt 都是一個獨立工作單元，產出一個 Python 檔案。

## 三階段流程

```
┌──────────────────────┐    status=watch    ┌──────────────────────┐    active/retired    ┌──────────────────────┐
│  discover_wallets.py │  ───────────────>  │  promote_wallets.py  │  ──────────────────>  │   wallet_scorer.py   │
└──────────────────────┘                    └──────────────────────┘                       └──────────────────────┘
   撒網抓候選                                      長窗口回測晉升                                持續跟單後再評估
   (外部 API / CSV)                                (外部歷史，90-180d)                          (自家 trades.db)
   docs/prompts/                                   docs/prompts/                                 已存在，不用動
   discover-wallets-prompt.md                      promote-wallets-prompt.md                    (wallet_scorer.py)
```

## 為什麼分三階段

| 階段 | 職責 | 資料源 | 輸出 status |
|------|------|--------|-------------|
| **Discover** | 撒大網，寬閾值，盡量多候選 | GMGN / Birdeye / Dune CSV | `watch` |
| **Promote** | 長窗口回測，Sharpe 評分，Sybil 合併 | GMGN 歷史端點 / Dune CSV | `active` / `watch` / `retired` |
| **Scorer**（既存） | 跟單後根據真實表現決定 keep/watch/retire | 自家 `trades.db` | `active` / `watch` / `retired` |

第一二階段不用自家 DB 因為候選錢包還沒被跟單過。第三階段才用真實跟單結果。

## Prompt 對應表

| 檔案 | 產出 | 執行者 |
|------|------|--------|
| `discover-wallets-prompt.md` | `scripts/discover_wallets.py` | Claude Sonnet |
| `promote-wallets-prompt.md` | `scripts/promote_wallets.py` | Claude Sonnet |

既有的 `wallet_scorer.py` 不需要新 prompt，已存在於 repo 根目錄。

## 執行順序（上線後）

```bash
# 1. 每天/每週跑一次 discover，補充 watch 名單
python scripts/discover_wallets.py --source all --limit 50 --csv ./dune_eth_180d.csv

# 2. 每週跑一次 promote，晉升 / 淘汰 watch 名單
python scripts/promote_wallets.py --chain all --csv ./dune_eth_180d.csv

# 3. wallet_scorer.py 由主程式 main.py 持續觸發（不在本 pipeline 範圍）
```

## 共同規範

所有腳本共享：

- **原始 response 快取**：`data/raw/{source}/{timestamp}.json`。
- **HTTP**：`httpx` 同步 client、`timeout=10s`、retry 3 次指數退避。
- **函式層次**：fetch → normalize → filter/score → persist，每層純函式可獨立 import。
- **immutability**：所有 dataclass frozen，用 `dataclasses.replace` 產生新物件。
- **缺值策略**：寧可保守標記（sentinel）也不造假數值。
- **錯誤處理**：不 silent fail，所有錯誤 print 來源 + address + 原因。
- **不寫 unit test**（探索腳本）但所有純函式可 import。
