import os
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise ValueError(f'Missing required environment variable: {key}')
    return value


def _optional(key: str) -> str | None:
    value = os.getenv(key)
    return value if value else None


def _parse_optional_int(key: str) -> int | None:
    value = _optional(key)
    return int(value) if value else None


def _parse_weather_districts() -> list[str]:
    districts_value = _optional('WEATHER_DISTRICTS')
    legacy_district = _optional('WEATHER_DISTRICT')
    raw_value = districts_value if districts_value is not None else legacy_district
    source_value = raw_value or '文山區,小港區'
    return [district.strip() for district in source_value.split(',') if district.strip()]


TELEGRAM_BOT_TOKEN = _require('TELEGRAM_BOT_TOKEN')
TELEGRAM_GROUP_ID = _parse_optional_int('TELEGRAM_GROUP_ID')
CWA_API_KEY = _optional('CWA_API_KEY')
GEMINI_API_KEY = _optional('GEMINI_API_KEY')
WEATHER_DISTRICTS = _parse_weather_districts()
MORNING_SEND_HOUR = int(os.getenv('MORNING_SEND_HOUR', '7'))
MORNING_SEND_MINUTE = int(os.getenv('MORNING_SEND_MINUTE', '0'))
