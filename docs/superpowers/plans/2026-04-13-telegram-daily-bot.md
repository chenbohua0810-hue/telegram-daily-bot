# Telegram 天氣新聞日報 Bot 實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立一個 Python Telegram Bot，每天早上自動發送台灣區級天氣預報，並支援手動指令觸發 AI 整理的新聞摘要，部署於 Zeabur，全程使用免費服務。

**Architecture:** 模組化架構，各層職責分離：`weather/` 處理 CWA API、`news/` 處理 RSS 與 Throk、`ai/` 處理 Gemini 摘要、`bot/` 處理 Telegram 指令與格式化、`scheduler/` 處理定時任務。各模組透過回傳資料結構溝通，不直接互相 import 業務邏輯。

**Tech Stack:** Python 3.11+、python-telegram-bot 20+（async）、APScheduler 3.x（AsyncIOScheduler）、feedparser、google-generativeai、httpx、python-dotenv、pytest + pytest-asyncio

---

## 檔案結構總覽

```
telegram-daily-bot/
├── config.py                  # 環境變數讀取（單一來源）
├── requirements.txt
├── .env.example
├── zeabur.json
├── bot/
│   ├── __init__.py
│   ├── main.py                # 入口點：啟動 bot + scheduler
│   ├── handlers.py            # /news, /weather 非同步指令處理
│   └── formatter.py           # 格式化天氣/新聞為 Telegram Markdown
├── weather/
│   ├── __init__.py
│   └── cwa.py                 # CWA 開放資料 API 封裝
├── news/
│   ├── __init__.py
│   ├── rss.py                 # RSS Feed 抓取與解析
│   └── throk.py               # Throk AI API 封裝（Threads 熱門）
├── ai/
│   ├── __init__.py
│   └── gemini.py              # Gemini Flash 新聞摘要
├── scheduler/
│   ├── __init__.py
│   └── jobs.py                # APScheduler 定時任務定義
└── tests/
    ├── conftest.py
    ├── test_cwa.py
    ├── test_rss.py
    ├── test_throk.py
    ├── test_gemini.py
    ├── test_formatter.py
    └── test_handlers.py
```

---

## Task 1: 專案初始化

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `config.py`
- Create: `zeabur.json`
- Create: `bot/__init__.py`, `weather/__init__.py`, `news/__init__.py`, `ai/__init__.py`, `scheduler/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: 建立目錄結構**

```bash
mkdir -p telegram-daily-bot/{bot,weather,news,ai,scheduler,tests}
cd telegram-daily-bot
touch bot/__init__.py weather/__init__.py news/__init__.py ai/__init__.py scheduler/__init__.py
```

- [ ] **Step 2: 建立 requirements.txt**

```text
python-telegram-bot==20.7
APScheduler==3.10.4
feedparser==6.0.11
google-generativeai==0.7.2
httpx==0.27.0
python-dotenv==1.0.1
pytz==2024.1
pytest==8.2.0
pytest-asyncio==0.23.6
pytest-mock==3.14.0
```

- [ ] **Step 3: 建立 .env.example**

```env
TELEGRAM_BOT_TOKEN=your_bot_token_from_botfather
TELEGRAM_GROUP_ID=-1001234567890
CWA_API_KEY=your_cwa_api_key
THROK_API_KEY=your_throk_api_key
GEMINI_API_KEY=your_gemini_api_key_from_google_ai_studio
WEATHER_DISTRICT=大安區
MORNING_SEND_HOUR=7
MORNING_SEND_MINUTE=0
```

- [ ] **Step 4: 建立 config.py**

```python
import os
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise ValueError(f"Missing required environment variable: {key}")
    return value


TELEGRAM_BOT_TOKEN = _require("TELEGRAM_BOT_TOKEN")
TELEGRAM_GROUP_ID = int(_require("TELEGRAM_GROUP_ID"))
CWA_API_KEY = _require("CWA_API_KEY")
THROK_API_KEY = _require("THROK_API_KEY")
GEMINI_API_KEY = _require("GEMINI_API_KEY")
WEATHER_DISTRICT = os.getenv("WEATHER_DISTRICT", "大安區")
MORNING_SEND_HOUR = int(os.getenv("MORNING_SEND_HOUR", "7"))
MORNING_SEND_MINUTE = int(os.getenv("MORNING_SEND_MINUTE", "0"))
```

- [ ] **Step 5: 建立 zeabur.json**

```json
{
  "build": {
    "command": "pip install -r requirements.txt"
  },
  "start": {
    "command": "python bot/main.py"
  }
}
```

- [ ] **Step 6: 建立 tests/conftest.py**

```python
import pytest
import os

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token")
os.environ.setdefault("TELEGRAM_GROUP_ID", "-1001234567890")
os.environ.setdefault("CWA_API_KEY", "test_cwa_key")
os.environ.setdefault("THROK_API_KEY", "test_throk_key")
os.environ.setdefault("GEMINI_API_KEY", "test_gemini_key")
os.environ.setdefault("WEATHER_DISTRICT", "大安區")
```

- [ ] **Step 7: 安裝依賴**

```bash
pip install -r requirements.txt
```

- [ ] **Step 8: Commit**

```bash
git init
git add .
git commit -m "chore: initial project setup with config and dependencies"
```

---

## Task 2: 天氣模組（CWA API）

**Files:**
- Create: `weather/cwa.py`
- Create: `tests/test_cwa.py`

CWA 開放資料平台申請金鑰：https://opendata.cwa.gov.tw/userLogin
Dataset ID：`F-D0047-089`（全台鄉鎮市區未來 48 小時天氣預報）

- [ ] **Step 1: 撰寫失敗測試**

建立 `tests/test_cwa.py`：

```python
import pytest
from unittest.mock import patch, AsyncMock
from weather.cwa import fetch_district_weather, WeatherData


@pytest.mark.asyncio
async def test_fetch_district_weather_returns_weather_data():
    mock_response = {
        "records": {
            "locations": [{
                "location": [{
                    "locationName": "大安區",
                    "weatherElement": [
                        {
                            "elementName": "Wx",
                            "time": [{"startTime": "2026-04-13 06:00:00", "elementValue": [{"value": "晴天"}]}]
                        },
                        {
                            "elementName": "MaxT",
                            "time": [{"startTime": "2026-04-13 06:00:00", "elementValue": [{"value": "28"}]}]
                        },
                        {
                            "elementName": "MinT",
                            "time": [{"startTime": "2026-04-13 06:00:00", "elementValue": [{"value": "22"}]}]
                        },
                        {
                            "elementName": "PoP12h",
                            "time": [{"startTime": "2026-04-13 06:00:00", "elementValue": [{"value": "10"}]}]
                        }
                    ]
                }]
            }]
        }
    }

    with patch("weather.cwa.httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=AsyncMock(
                status_code=200,
                json=lambda: mock_response,
                raise_for_status=lambda: None
            )
        )
        result = await fetch_district_weather("大安區", "test_key")

    assert isinstance(result, WeatherData)
    assert result.district == "大安區"
    assert result.description == "晴天"
    assert result.max_temp == 28
    assert result.min_temp == 22
    assert result.rain_prob == 10


@pytest.mark.asyncio
async def test_fetch_district_weather_raises_on_api_error():
    with patch("weather.cwa.httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=Exception("API error")
        )
        with pytest.raises(Exception, match="API error"):
            await fetch_district_weather("大安區", "test_key")
```

- [ ] **Step 2: 執行測試確認失敗**

```bash
pytest tests/test_cwa.py -v
```

預期：FAIL，`ImportError: cannot import name 'fetch_district_weather'`

- [ ] **Step 3: 實作 weather/cwa.py**

```python
from dataclasses import dataclass
import httpx

CWA_BASE_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-D0047-089"


@dataclass
class WeatherData:
    district: str
    description: str
    max_temp: int
    min_temp: int
    rain_prob: int


def _extract_element(elements: list, name: str) -> str:
    for el in elements:
        if el["elementName"] == name:
            return el["time"][0]["elementValue"][0]["value"]
    return "N/A"


async def fetch_district_weather(district: str, api_key: str) -> WeatherData:
    params = {
        "Authorization": api_key,
        "locationName": district,
        "elementName": "Wx,MaxT,MinT,PoP12h",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(CWA_BASE_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    location = data["records"]["locations"][0]["location"][0]
    elements = location["weatherElement"]

    return WeatherData(
        district=district,
        description=_extract_element(elements, "Wx"),
        max_temp=int(_extract_element(elements, "MaxT")),
        min_temp=int(_extract_element(elements, "MinT")),
        rain_prob=int(_extract_element(elements, "PoP12h")),
    )
```

- [ ] **Step 4: 執行測試確認通過**

```bash
pytest tests/test_cwa.py -v
```

預期：2 passed

- [ ] **Step 5: Commit**

```bash
git add weather/cwa.py tests/test_cwa.py
git commit -m "feat: add CWA weather API module"
```

---

## Task 3: RSS 新聞模組

**Files:**
- Create: `news/rss.py`
- Create: `tests/test_rss.py`

- [ ] **Step 1: 撰寫失敗測試**

建立 `tests/test_rss.py`：

```python
import pytest
from unittest.mock import patch, MagicMock
from news.rss import fetch_rss_news, NewsItem

MOCK_FEED = MagicMock()
MOCK_FEED.entries = [
    MagicMock(
        title="台灣經濟成長超預期",
        link="https://example.com/1",
        summary="台灣第一季GDP成長達5.2%...",
        published="Mon, 13 Apr 2026 08:00:00 +0800"
    ),
    MagicMock(
        title="AI 科技新突破",
        link="https://example.com/2",
        summary="Google 發布新模型...",
        published="Mon, 13 Apr 2026 07:30:00 +0800"
    ),
]


def test_fetch_rss_news_returns_news_items():
    with patch("news.rss.feedparser.parse", return_value=MOCK_FEED):
        results = fetch_rss_news("https://fake-rss.com/feed.xml", limit=2)

    assert len(results) == 2
    assert isinstance(results[0], NewsItem)
    assert results[0].title == "台灣經濟成長超預期"
    assert results[0].url == "https://example.com/1"
    assert "GDP" in results[0].summary


def test_fetch_rss_news_respects_limit():
    with patch("news.rss.feedparser.parse", return_value=MOCK_FEED):
        results = fetch_rss_news("https://fake-rss.com/feed.xml", limit=1)

    assert len(results) == 1


def test_fetch_all_sources_aggregates_results():
    with patch("news.rss.feedparser.parse", return_value=MOCK_FEED):
        from news.rss import fetch_all_sources
        results = fetch_all_sources(limit_per_source=1)

    assert len(results) >= 1
    assert all(isinstance(item, NewsItem) for item in results)
```

- [ ] **Step 2: 執行測試確認失敗**

```bash
pytest tests/test_rss.py -v
```

預期：FAIL，`ImportError`

- [ ] **Step 3: 實作 news/rss.py**

```python
from dataclasses import dataclass
import feedparser

RSS_SOURCES = [
    "https://news.ltn.com.tw/rss/all.xml",           # 自由時報
    "https://feeds.feedburner.com/rsscna",             # 中央社
    "https://feeds.bbci.co.uk/zhongwen/trad/rss.xml", # BBC 中文
    "https://news.google.com/rss?hl=zh-TW&gl=TW&ceid=TW:zh-Hant",  # Google 新聞
]


@dataclass
class NewsItem:
    title: str
    url: str
    summary: str
    source: str


def fetch_rss_news(feed_url: str, limit: int = 5) -> list[NewsItem]:
    feed = feedparser.parse(feed_url)
    items = []
    for entry in feed.entries[:limit]:
        summary = getattr(entry, "summary", "") or ""
        items.append(NewsItem(
            title=entry.title,
            url=entry.link,
            summary=summary[:200],
            source=feed_url,
        ))
    return items


def fetch_all_sources(limit_per_source: int = 3) -> list[NewsItem]:
    all_items = []
    for url in RSS_SOURCES:
        try:
            items = fetch_rss_news(url, limit=limit_per_source)
            all_items.extend(items)
        except Exception:
            continue
    return all_items
```

- [ ] **Step 4: 執行測試確認通過**

```bash
pytest tests/test_rss.py -v
```

預期：3 passed

- [ ] **Step 5: Commit**

```bash
git add news/rss.py tests/test_rss.py
git commit -m "feat: add RSS news fetcher module"
```

---

## Task 4: Throk AI 模組

**Files:**
- Create: `news/throk.py`
- Create: `tests/test_throk.py`

> **注意：** Throk AI 目前為 SaaS 平台，公開 REST API 文件未完全公開。本模組以常見 REST 模式實作，若 API 結構不同請依實際回應調整。若 Throk 無法使用，模組會靜默略過並回傳空列表。

- [ ] **Step 1: 撰寫失敗測試**

建立 `tests/test_throk.py`：

```python
import pytest
from unittest.mock import patch, AsyncMock
from news.throk import fetch_trending_threads, TrendingPost


@pytest.mark.asyncio
async def test_fetch_trending_threads_returns_posts():
    mock_response = {
        "data": [
            {"text": "AI 科技話題引發討論", "engagement": 1500, "url": "https://threads.net/p/abc"},
            {"text": "台灣選舉最新動態", "engagement": 1200, "url": "https://threads.net/p/def"},
        ]
    }

    with patch("news.throk.httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=AsyncMock(
                status_code=200,
                json=lambda: mock_response,
                raise_for_status=lambda: None
            )
        )
        results = await fetch_trending_threads("test_key", limit=2)

    assert len(results) == 2
    assert isinstance(results[0], TrendingPost)
    assert results[0].text == "AI 科技話題引發討論"
    assert results[0].engagement == 1500


@pytest.mark.asyncio
async def test_fetch_trending_threads_returns_empty_on_error():
    with patch("news.throk.httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=Exception("API unavailable")
        )
        results = await fetch_trending_threads("test_key", limit=3)

    assert results == []
```

- [ ] **Step 2: 執行測試確認失敗**

```bash
pytest tests/test_throk.py -v
```

預期：FAIL，`ImportError`

- [ ] **Step 3: 實作 news/throk.py**

```python
from dataclasses import dataclass
import httpx

THROK_API_BASE = "https://api.throk.ai/v1"


@dataclass
class TrendingPost:
    text: str
    engagement: int
    url: str


async def fetch_trending_threads(api_key: str, limit: int = 3) -> list[TrendingPost]:
    """
    Fetch trending Threads posts from Throk AI.
    Returns empty list on any error to ensure graceful degradation.
    """
    try:
        headers = {"Authorization": f"Bearer {api_key}"}
        params = {"limit": limit}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{THROK_API_BASE}/trending",
                headers=headers,
                params=params
            )
            resp.raise_for_status()
            data = resp.json()

        return [
            TrendingPost(
                text=item["text"],
                engagement=item.get("engagement", 0),
                url=item.get("url", ""),
            )
            for item in data.get("data", [])[:limit]
        ]
    except Exception:
        return []
```

- [ ] **Step 4: 執行測試確認通過**

```bash
pytest tests/test_throk.py -v
```

預期：2 passed

- [ ] **Step 5: Commit**

```bash
git add news/throk.py tests/test_throk.py
git commit -m "feat: add Throk AI trending threads module with graceful fallback"
```

---

## Task 5: Gemini AI 摘要模組

**Files:**
- Create: `ai/gemini.py`
- Create: `tests/test_gemini.py`

- [ ] **Step 1: 撰寫失敗測試**

建立 `tests/test_gemini.py`：

```python
import pytest
from unittest.mock import patch, MagicMock
from ai.gemini import summarize_news
from news.rss import NewsItem
from news.throk import TrendingPost

NEWS_ITEMS = [
    NewsItem(title="台灣 GDP 成長", url="https://example.com/1", summary="台灣第一季GDP成長5.2%", source="ltn"),
    NewsItem(title="AI 新突破", url="https://example.com/2", summary="Google 發布 Gemini 2.0", source="bbc"),
]

TRENDING_POSTS = [
    TrendingPost(text="台灣科技產業話題", engagement=2000, url="https://threads.net/p/abc"),
]


def test_summarize_news_returns_string():
    mock_model = MagicMock()
    mock_model.generate_content.return_value = MagicMock(text="📰 今日新聞摘要\n1. 台灣 GDP 成長...")

    with patch("ai.gemini.genai.GenerativeModel", return_value=mock_model):
        result = summarize_news(NEWS_ITEMS, TRENDING_POSTS, "test_key")

    assert isinstance(result, str)
    assert len(result) > 0
    mock_model.generate_content.assert_called_once()


def test_summarize_news_returns_fallback_on_error():
    with patch("ai.gemini.genai.GenerativeModel", side_effect=Exception("API error")):
        result = summarize_news(NEWS_ITEMS, TRENDING_POSTS, "test_key")

    assert "台灣 GDP 成長" in result
    assert "AI 新突破" in result
```

- [ ] **Step 2: 執行測試確認失敗**

```bash
pytest tests/test_gemini.py -v
```

預期：FAIL，`ImportError`

- [ ] **Step 3: 實作 ai/gemini.py**

```python
import google.generativeai as genai
from news.rss import NewsItem
from news.throk import TrendingPost

PROMPT_TEMPLATE = """你是一個繁體中文新聞編輯。請將以下新聞整理成簡潔的日報摘要，使用繁體中文，格式為 Telegram Markdown。

新聞來源：
{news_section}

Threads 熱門話題：
{threads_section}

請輸出：
1. 5 則最重要的新聞（每則一行，含簡短說明）
2. 3 則 Threads 熱門話題

格式範例：
📰 *今日新聞*
• [標題](連結) — 一句話摘要
...

🔥 *Threads 熱門*
• 話題內容
..."""


def _build_prompt(news_items: list[NewsItem], trending: list[TrendingPost]) -> str:
    news_section = "\n".join(
        f"- {item.title}: {item.summary} ({item.url})"
        for item in news_items
    )
    threads_section = "\n".join(
        f"- {post.text} (互動：{post.engagement})"
        for post in trending
    ) or "（無資料）"

    return PROMPT_TEMPLATE.format(
        news_section=news_section,
        threads_section=threads_section
    )


def _fallback_summary(news_items: list[NewsItem], trending: list[TrendingPost]) -> str:
    lines = ["📰 *今日新聞*（摘要服務暫時不可用）"]
    for item in news_items[:5]:
        lines.append(f"• [{item.title}]({item.url})")
    if trending:
        lines.append("\n🔥 *Threads 熱門*")
        for post in trending[:3]:
            lines.append(f"• {post.text}")
    return "\n".join(lines)


def summarize_news(
    news_items: list[NewsItem],
    trending: list[TrendingPost],
    api_key: str
) -> str:
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = _build_prompt(news_items, trending)
        response = model.generate_content(prompt)
        return response.text
    except Exception:
        return _fallback_summary(news_items, trending)
```

- [ ] **Step 4: 執行測試確認通過**

```bash
pytest tests/test_gemini.py -v
```

預期：2 passed

- [ ] **Step 5: Commit**

```bash
git add ai/gemini.py tests/test_gemini.py
git commit -m "feat: add Gemini Flash news summarizer with fallback"
```

---

## Task 6: 訊息格式化模組

**Files:**
- Create: `bot/formatter.py`
- Create: `tests/test_formatter.py`

- [ ] **Step 1: 撰寫失敗測試**

建立 `tests/test_formatter.py`：

```python
from bot.formatter import format_weather_message
from weather.cwa import WeatherData


def test_format_weather_message_contains_district():
    data = WeatherData(
        district="大安區",
        description="多雲時晴",
        max_temp=28,
        min_temp=20,
        rain_prob=20,
    )
    result = format_weather_message(data)

    assert "大安區" in result
    assert "多雲時晴" in result
    assert "28" in result
    assert "20" in result
    assert "20%" in result


def test_format_weather_message_is_string():
    data = WeatherData(
        district="信義區",
        description="晴天",
        max_temp=30,
        min_temp=22,
        rain_prob=0,
    )
    result = format_weather_message(data)
    assert isinstance(result, str)
    assert len(result) > 0
```

- [ ] **Step 2: 執行測試確認失敗**

```bash
pytest tests/test_formatter.py -v
```

預期：FAIL，`ImportError`

- [ ] **Step 3: 實作 bot/formatter.py**

```python
from weather.cwa import WeatherData
import pytz
from datetime import datetime

TZ = pytz.timezone("Asia/Taipei")


def _now_str() -> str:
    return datetime.now(TZ).strftime("%Y/%m/%d %H:%M")


def format_weather_message(data: WeatherData) -> str:
    rain_icon = "🌧️" if data.rain_prob >= 50 else "☀️"
    return (
        f"🌤️ *{data.district} 天氣早報*\n"
        f"🕐 {_now_str()}\n\n"
        f"天氣：{data.description}\n"
        f"🌡️ 溫度：{data.min_temp}°C — {data.max_temp}°C\n"
        f"{rain_icon} 降雨機率：{data.rain_prob}%"
    )
```

- [ ] **Step 4: 執行測試確認通過**

```bash
pytest tests/test_formatter.py -v
```

預期：2 passed

- [ ] **Step 5: Commit**

```bash
git add bot/formatter.py tests/test_formatter.py
git commit -m "feat: add Telegram message formatter for weather"
```

---

## Task 7: Telegram 指令處理

**Files:**
- Create: `bot/handlers.py`
- Create: `tests/test_handlers.py`

- [ ] **Step 1: 撰寫失敗測試**

建立 `tests/test_handlers.py`：

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from bot.handlers import weather_command, news_command


@pytest.mark.asyncio
async def test_weather_command_sends_message():
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    mock_weather = MagicMock()
    mock_weather.district = "大安區"
    mock_weather.description = "晴天"
    mock_weather.max_temp = 28
    mock_weather.min_temp = 20
    mock_weather.rain_prob = 10

    with patch("bot.handlers.fetch_district_weather", AsyncMock(return_value=mock_weather)), \
         patch("bot.handlers.format_weather_message", return_value="天氣訊息"):
        await weather_command(update, context)

    update.message.reply_text.assert_called_once_with("天氣訊息", parse_mode="Markdown")


@pytest.mark.asyncio
async def test_news_command_sends_message():
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    with patch("bot.handlers.fetch_all_sources", return_value=[]), \
         patch("bot.handlers.fetch_trending_threads", AsyncMock(return_value=[])), \
         patch("bot.handlers.summarize_news", return_value="📰 今日新聞"):
        await news_command(update, context)

    update.message.reply_text.assert_called_once_with("📰 今日新聞", parse_mode="Markdown")
```

- [ ] **Step 2: 執行測試確認失敗**

```bash
pytest tests/test_handlers.py -v
```

預期：FAIL，`ImportError`

- [ ] **Step 3: 實作 bot/handlers.py**

```python
from telegram import Update
from telegram.ext import ContextTypes
import config
from weather.cwa import fetch_district_weather
from news.rss import fetch_all_sources
from news.throk import fetch_trending_threads
from ai.gemini import summarize_news
from bot.formatter import format_weather_message


async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    district = args[0] if args else config.WEATHER_DISTRICT

    try:
        weather = await fetch_district_weather(district, config.CWA_API_KEY)
        message = format_weather_message(weather)
    except Exception as e:
        message = f"⚠️ 無法取得 {district} 的天氣資訊，請稍後再試。"

    await update.message.reply_text(message, parse_mode="Markdown")


async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("⏳ 正在整理今日新聞，請稍候...", parse_mode="Markdown")

    news_items = fetch_all_sources(limit_per_source=3)
    trending = await fetch_trending_threads(config.THROK_API_KEY, limit=3)
    summary = summarize_news(news_items, trending, config.GEMINI_API_KEY)

    await update.message.reply_text(summary, parse_mode="Markdown")
```

- [ ] **Step 4: 執行測試確認通過**

```bash
pytest tests/test_handlers.py -v
```

預期：2 passed

- [ ] **Step 5: Commit**

```bash
git add bot/handlers.py tests/test_handlers.py
git commit -m "feat: add Telegram command handlers for /weather and /news"
```

---

## Task 8: 排程器

**Files:**
- Create: `scheduler/jobs.py`

- [ ] **Step 1: 實作 scheduler/jobs.py**

（此模組整合所有模組，不需獨立 unit test，已由各模組測試覆蓋）

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot
import pytz
import config
from weather.cwa import fetch_district_weather
from bot.formatter import format_weather_message

TZ = pytz.timezone("Asia/Taipei")


async def send_morning_weather(bot: Bot) -> None:
    try:
        weather = await fetch_district_weather(config.WEATHER_DISTRICT, config.CWA_API_KEY)
        message = format_weather_message(weather)
    except Exception:
        message = f"⚠️ 早報天氣資料暫時無法取得，請使用 /weather 手動查詢。"

    await bot.send_message(
        chat_id=config.TELEGRAM_GROUP_ID,
        text=message,
        parse_mode="Markdown"
    )


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=TZ)
    scheduler.add_job(
        send_morning_weather,
        trigger="cron",
        hour=config.MORNING_SEND_HOUR,
        minute=config.MORNING_SEND_MINUTE,
        args=[bot],
        id="morning_weather",
        replace_existing=True,
    )
    return scheduler
```

- [ ] **Step 2: Commit**

```bash
git add scheduler/jobs.py
git commit -m "feat: add APScheduler daily weather job"
```

---

## Task 9: 主程式入口

**Files:**
- Create: `bot/main.py`

- [ ] **Step 1: 實作 bot/main.py**

```python
import logging
from telegram.ext import Application, CommandHandler
import config
from bot.handlers import weather_command, news_command
from scheduler.jobs import setup_scheduler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


async def post_init(application: Application) -> None:
    scheduler = setup_scheduler(application.bot)
    scheduler.start()
    logger.info("Scheduler started. Morning weather at %02d:%02d Asia/Taipei",
                config.MORNING_SEND_HOUR, config.MORNING_SEND_MINUTE)


def main() -> None:
    app = (
        Application.builder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("weather", weather_command))
    app.add_handler(CommandHandler("news", news_command))

    logger.info("Bot starting...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 執行所有測試確認通過**

```bash
pytest tests/ -v --tb=short
```

預期：所有測試通過

- [ ] **Step 3: 本機測試（需要真實 API 金鑰）**

```bash
cp .env.example .env
# 填入真實的 API 金鑰
python bot/main.py
```

在 Telegram 群組輸入 `/weather` 和 `/news` 確認回應正常。

- [ ] **Step 4: Commit**

```bash
git add bot/main.py
git commit -m "feat: add main entry point with bot and scheduler initialization"
```

---

## Task 10: Zeabur 部署

- [ ] **Step 1: 確認 Zeabur 帳號與專案**

前往 https://zeabur.com，建立新專案，選擇 Python 環境。

- [ ] **Step 2: 推送至 GitHub**

```bash
git remote add origin https://github.com/your-username/telegram-daily-bot.git
git push -u origin main
```

- [ ] **Step 3: 在 Zeabur 設定環境變數**

於 Zeabur 控制台 → Variables，依 `.env.example` 填入所有環境變數：
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_GROUP_ID`
- `CWA_API_KEY`
- `THROK_API_KEY`
- `GEMINI_API_KEY`
- `WEATHER_DISTRICT`
- `MORNING_SEND_HOUR`
- `MORNING_SEND_MINUTE`

- [ ] **Step 4: 部署並確認 Log**

Zeabur 連接 GitHub repo 後自動部署，確認 Log 顯示：
```
Bot starting...
Scheduler started. Morning weather at 07:00 Asia/Taipei
```

- [ ] **Step 5: 最終 E2E 驗證**

於 Telegram 群組：
1. 輸入 `/weather` → 應回傳天氣訊息
2. 輸入 `/weather 信義區` → 應回傳信義區天氣
3. 輸入 `/news` → 應先回傳「整理中」，後回傳新聞摘要
4. 等待隔日 07:00 → 確認自動天氣早報發送

---

## API 金鑰申請清單

| 服務 | 申請網址 |
|------|---------|
| CWA 開放資料 | https://opendata.cwa.gov.tw/userLogin |
| Throk AI | https://www.throk.ai/（免費方案） |
| Gemini Flash | https://aistudio.google.com/app/apikey |
| Telegram Bot | 在 Telegram 找 @BotFather，輸入 `/newbot` |
