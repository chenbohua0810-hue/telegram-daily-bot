from datetime import datetime
from zoneinfo import ZoneInfo

from weather.cwa import WeatherData

TZ = ZoneInfo('Asia/Taipei')


def _now_str() -> str:
    return datetime.now(TZ).strftime('%Y/%m/%d %H:%M')


def format_weather_message(data: WeatherData) -> str:
    rain_icon = '🌧️' if data.rain_prob >= 50 else '☀️'
    return (
        f'🌤️ *{data.district} 天氣早報*\n'
        f'🕐 {_now_str()}\n\n'
        f'天氣：{data.description}\n'
        f'🌡️ 溫度：{data.min_temp}°C — {data.max_temp}°C\n'
        f'{rain_icon} 降雨機率：{data.rain_prob}%'
    )
