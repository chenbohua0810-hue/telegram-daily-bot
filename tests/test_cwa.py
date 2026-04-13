from unittest.mock import AsyncMock, patch

import pytest

from weather.cwa import WeatherData, WeatherLookupError, fetch_district_weather


@pytest.mark.asyncio
async def test_fetch_district_weather_returns_weather_data():
    mock_response = {
        'records': {
            'locations': [{
                'location': [{
                    'locationName': '大安區',
                    'weatherElement': [
                        {
                            'elementName': 'Wx',
                            'time': [{'startTime': '2026-04-13 06:00:00', 'elementValue': [{'value': '晴天'}]}],
                        },
                        {
                            'elementName': 'MaxT',
                            'time': [{'startTime': '2026-04-13 06:00:00', 'elementValue': [{'value': '28'}]}],
                        },
                        {
                            'elementName': 'MinT',
                            'time': [{'startTime': '2026-04-13 06:00:00', 'elementValue': [{'value': '22'}]}],
                        },
                        {
                            'elementName': 'PoP12h',
                            'time': [{'startTime': '2026-04-13 06:00:00', 'elementValue': [{'value': '10'}]}],
                        },
                    ],
                }],
            }],
        }
    }

    with patch('weather.cwa.httpx.AsyncClient') as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=AsyncMock(
                status_code=200,
                json=lambda: mock_response,
                raise_for_status=lambda: None,
            )
        )
        result = await fetch_district_weather('大安區', 'test_key')

    assert isinstance(result, WeatherData)
    assert result.district == '大安區'
    assert result.description == '晴天'
    assert result.max_temp == 28
    assert result.min_temp == 22
    assert result.rain_prob == 10


@pytest.mark.asyncio
async def test_fetch_district_weather_raises_on_api_error():
    with patch('weather.cwa.httpx.AsyncClient') as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=Exception('API error')
        )
        with pytest.raises(Exception, match='API error'):
            await fetch_district_weather('大安區', 'test_key')


@pytest.mark.asyncio
async def test_fetch_district_weather_raises_on_missing_location():
    mock_response = {
        'records': {
            'locations': [{
                'location': [],
            }],
        }
    }

    with patch('weather.cwa.httpx.AsyncClient') as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=AsyncMock(
                status_code=200,
                json=lambda: mock_response,
                raise_for_status=lambda: None,
            )
        )
        with pytest.raises(WeatherLookupError, match='查無 文山區 的天氣資料'):
            await fetch_district_weather('文山區', 'test_key')
