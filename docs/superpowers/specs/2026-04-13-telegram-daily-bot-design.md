# Telegram 天氣新聞日報 Bot — 設計文件

**日期：** 2026-04-13
**狀態：** 已核准，待實作

---

## 1. 專案目標

建立一個 Telegram Bot，每天自動發送天氣早報給小群組，並支援手動觸發新聞摘要。所有使用的服務皆為免費方案，部署於 Zeabur 雲端平台。

---

## 2. 使用者需求

| 需求 | 說明 |
|------|------|
| 對象 | 小群組（家人/朋友） |
| 天氣 | 每天早上 07:00 自動發送，精確到台灣行政區（鄉鎮區） |
| 新聞 | 手動觸發，來源為 RSS Feed + Throk AI（Threads 熱門） |
| AI 整理 | 新聞由 Gemini Flash 摘要後再發送 |
| 費用 | 全部使用免費方案，零費用 |
| 語言 | Python |
| 部署 | Zeabur |

---

## 3. 系統架構

```
資料來源層                AI 處理層           傳送層
──────────────           ─────────────       ──────────
RSS Feed（台灣+國際）──┐
                        ├──→ Gemini Flash ──→ Telegram Bot ──→ 群組
Throk AI（Threads）  ──┘    (整理/摘要)

CWA API（中央氣象署）────────────────────→ Telegram Bot ──→ 群組
（格式固定，不經 AI）
```

---

## 4. 功能規格

### 4.1 自動天氣早報

- **觸發：** 每天 07:00（台灣時間，UTC+8）
- **資料來源：** 中央氣象署（CWA）開放資料 API
- **精度：** 鄉鎮區層級（如：大安區、信義區）
- **內容：**
  - 今日天氣概況（天氣現象、溫度範圍、降雨機率）
  - 明日天氣預報
- **格式：** Telegram Markdown，結構清晰易讀

### 4.2 手動新聞快報（`/news`）

- **觸發：** 群組成員輸入 `/news` 指令
- **資料來源：**
  - RSS Feed：自由時報、中央社、BBC 中文（台灣+國際）
  - Throk AI：Threads 平台今日熱門貼文話題
- **AI 處理：** Gemini Flash 對以上內容去重、摘要、整理為中文重點
- **輸出：** 5 則重要新聞摘要 + 3 則 Threads 熱門話題

### 4.3 手動天氣查詢（`/weather <地區>`）

- **觸發：** 輸入 `/weather 大安區` 等指令
- **資料來源：** CWA API 即時查詢
- **輸出：** 指定區目前天氣狀況

---

## 5. 使用服務清單（全部免費）

| 服務 | 用途 | 免費額度 | 需要金鑰 |
|------|------|---------|---------|
| CWA 開放資料 API | 天氣資料 | 免費申請 | 是（免費） |
| RSS Feed | 新聞抓取 | 無限制 | 否 |
| Throk AI | Threads 熱門 | 50 credits/天 | 是（免費方案） |
| Gemini Flash | 新聞摘要 | 1,500 次/天 | 是（Google AI Studio） |
| Telegram Bot API | 傳送訊息 | 無限制 | 是（BotFather） |
| Zeabur | 部署平台 | 免費方案 | 是（帳號） |

---

## 6. 專案結構

```
telegram-daily-bot/
├── bot/
│   ├── main.py          # 入口點：啟動 bot + scheduler
│   ├── handlers.py      # Telegram 指令處理（/news, /weather）
│   └── formatter.py     # 訊息格式化（Telegram Markdown）
├── weather/
│   └── cwa.py           # 中央氣象署 API 封裝
├── news/
│   ├── rss.py           # RSS Feed 抓取與解析
│   └── throk.py         # Throk AI API 封裝
├── ai/
│   └── gemini.py        # Gemini Flash 摘要整理
├── scheduler/
│   └── jobs.py          # APScheduler 定時任務設定
├── config.py            # 環境變數讀取（dotenv）
├── requirements.txt     # Python 依賴套件
└── zeabur.json          # Zeabur 部署設定
```

---

## 7. 環境變數

```env
TELEGRAM_BOT_TOKEN=       # BotFather 申請
TELEGRAM_GROUP_ID=        # 群組 Chat ID
CWA_API_KEY=              # 中央氣象署開放資料金鑰
THROK_API_KEY=            # Throk AI 金鑰
GEMINI_API_KEY=           # Google AI Studio 金鑰
WEATHER_DISTRICT=         # 預設發送的區（如：大安區）
MORNING_SEND_TIME=07:00   # 早報發送時間（台灣時間）
```

---

## 8. 主要依賴套件

```
python-telegram-bot>=20.0
apscheduler>=3.10
feedparser              # RSS 解析
httpx                   # HTTP 請求
google-generativeai     # Gemini API
python-dotenv           # 環境變數
pytz                    # 時區處理
```

---

## 9. 資料流說明

### 天氣早報流程
1. APScheduler 在 07:00 觸發
2. `cwa.py` 呼叫 CWA API 取得指定區天氣
3. `formatter.py` 格式化為 Markdown 訊息
4. `main.py` 透過 Telegram Bot API 發送至群組

### 新聞快報流程
1. 使用者輸入 `/news`
2. `handlers.py` 接收指令
3. `rss.py` 並行抓取各 RSS 來源最新文章
4. `throk.py` 取得今日 Threads 熱門話題
5. `gemini.py` 送交 Gemini Flash 整理摘要
6. `formatter.py` 格式化輸出
7. 發送至群組

---

## 10. 錯誤處理策略

- API 呼叫失敗：記錄錯誤 log，發送簡短失敗通知至群組
- Throk 超過免費額度：跳過 Throk，僅發送 RSS 新聞
- Gemini 失敗：發送未整理的原始新聞標題作為備援
- 時區：所有排程以 `Asia/Taipei`（UTC+8）為基準

---

## 11. 部署（Zeabur）

- 使用 Zeabur Python 執行環境
- 環境變數於 Zeabur 控制台設定
- 持續運行（long-running process），不需要 webhook
- `zeabur.json` 指定啟動指令：`python bot/main.py`
