import os
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise ValueError(f'Missing required environment variable: {key}')
    return value


TELEGRAM_BOT_TOKEN = _require('TELEGRAM_BOT_TOKEN')
TELEGRAM_GROUP_ID = int(_require('TELEGRAM_GROUP_ID'))
CWA_API_KEY = _require('CWA_API_KEY')
GEMINI_API_KEY = _require('GEMINI_API_KEY')
WEATHER_DISTRICTS = [
    d.strip()
    for d in os.getenv('WEATHER_DISTRICTS', '文山區,小港區').split(',')
    if d.strip()
]
MORNING_SEND_HOUR = int(os.getenv('MORNING_SEND_HOUR', '7'))
MORNING_SEND_MINUTE = int(os.getenv('MORNING_SEND_MINUTE', '0'))
