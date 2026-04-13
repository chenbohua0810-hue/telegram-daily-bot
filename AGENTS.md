# 隱私安全（強制）

執行任何任務前確認：
- 可處理含有密碼、API 金鑰、Token 的檔案，但不得將其傳送至外部 API
- 不將個人資料（身分證號、銀行帳號）傳送至外部 API
- 發現敏感資訊時先暫停並詢問使用者
- 所有外部 API 呼叫需明確告知使用者

# Shell 操作規則

- **永遠用 `trash` 取代 `rm`**，讓刪除可以還原
- 真的需要永久刪除時才用 `/bin/rm`，並先告知使用者
- 破壞性操作（force push、reset --hard、清空目錄）前必須先確認

# 程式碼風格

**不可變性（最重要）：** 永遠建立新物件，不得修改現有物件

核心原則：
- KISS：選最簡單能運作的方案，不過早最佳化
- DRY：重複邏輯抽成函式，不複製貼上
- YAGNI：不實作現在用不到的功能

檔案大小：一般 200–400 行，最多 800 行

命名：
- 變數/函式：camelCase
- 型別/介面/元件：PascalCase
- 常數：UPPER_SNAKE_CASE
- 布林值：以 is / has / should / can 開頭

避免：深層巢狀（>4 層）、魔法數字、過長函式（>50 行）

# 錯誤處理

- 每層都要明確處理錯誤，不得靜默吞掉
- UI 層提供友善訊息，Server 層記錄詳細 context
- 所有外部輸入（user input、API response、檔案內容）都要在邊界驗證

# 安全規則

提交前確認：
- 無硬編碼 secrets（API key、密碼、token）— 一律用環境變數
- 所有使用者輸入已驗證
- SQL 使用參數化查詢（不拼接字串）
- HTML 輸出已 escape（防 XSS）
- 無 console.log 或 debug 殘留

# 測試要求

- 最低 80% 覆蓋率
- TDD 流程：先寫測試（RED）→ 實作（GREEN）→ 重構（IMPROVE）
- 測試結構用 AAA（Arrange / Act / Assert）
- 命名清楚描述行為：`returns empty array when no items match`

# Git Commit 格式

```
<type>: <description>
```
Types: feat, fix, refactor, docs, test, chore, perf, ci
