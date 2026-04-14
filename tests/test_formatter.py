from bot.formatter import format_weather_message
from weather.cwa import WeatherData


def test_format_weather_message_contains_district():
    data = WeatherData(
        district='大安區',
        description='多雲時晴',
        max_temp=28,
        min_temp=20,
        rain_prob=20,
    )
    result = format_weather_message(data)

    assert '大安區' in result
    assert '多雲時晴' in result
    assert '28' in result
    assert '20' in result
    assert '20%' in result


def test_format_weather_message_is_string():
    data = WeatherData(
        district='信義區',
        description='晴天',
        max_temp=30,
        min_temp=22,
        rain_prob=0,
    )
    result = format_weather_message(data)
    assert isinstance(result, str)
    assert len(result) > 0


def test_format_weather_message_handles_missing_rain_probability():
    data = WeatherData(
        district='文山區',
        description='多雲',
        max_temp=27,
        min_temp=21,
        rain_prob=None,
    )
    result = format_weather_message(data)

    assert '降雨機率：N/A' in result
