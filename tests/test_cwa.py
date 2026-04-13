from unittest.mock import AsyncMock, patch

import pytest

from weather.cwa import (
    CWA_BASE_URL,
    WeatherData,
    WeatherLookupError,
    fetch_district_weather,
)


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
        mock_get = AsyncMock(
            return_value=AsyncMock(
                status_code=200,
                json=lambda: mock_response,
                text='{}',
                raise_for_status=lambda: None,
            )
        )
        mock_client.return_value.__aenter__.return_value.get = mock_get
        result = await fetch_district_weather('大安區', 'test_key')

    assert isinstance(result, WeatherData)
    assert result.district == '大安區'
    assert result.description == '晴天'
    assert result.max_temp == 28
    assert result.min_temp == 22
    assert result.rain_prob == 10
    mock_get.assert_awaited_once_with(
        CWA_BASE_URL,
        params={
            'Authorization': 'test_key',
            'locationName': '大安區',
            'elementName': 'Weather,MaxTemperature,MinTemperature,ProbabilityOfPrecipitation',
        },
    )


@pytest.mark.asyncio
async def test_fetch_district_weather_supports_official_cwa_field_names():
    mock_response = {
        'records': {
            'Locations': [{
                'Location': [{
                    'LocationName': '文山區',
                    'WeatherElement': [
                        {
                            'ElementName': 'Weather',
                            'Time': [{
                                'StartTime': '2026-04-13 06:00:00',
                                'ElementValue': [{'Weather': '多雲'}],
                            }],
                        },
                        {
                            'ElementName': 'MaxTemperature',
                            'Time': [{
                                'StartTime': '2026-04-13 06:00:00',
                                'ElementValue': [{'MaxTemperature': '27'}],
                            }],
                        },
                        {
                            'ElementName': 'MinTemperature',
                            'Time': [{
                                'StartTime': '2026-04-13 06:00:00',
                                'ElementValue': [{'MinTemperature': '21'}],
                            }],
                        },
                        {
                            'ElementName': 'ProbabilityOfPrecipitation',
                            'Time': [{
                                'StartTime': '2026-04-13 06:00:00',
                                'ElementValue': [{'ProbabilityOfPrecipitation': '20'}],
                            }],
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
                text='{}',
                raise_for_status=lambda: None,
            )
        )
        result = await fetch_district_weather('文山區', 'test_key')

    assert isinstance(result, WeatherData)
    assert result.district == '文山區'
    assert result.description == '多雲'
    assert result.max_temp == 27
    assert result.min_temp == 21
    assert result.rain_prob == 20


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
                text='{}',
                raise_for_status=lambda: None,
            )
        )
        with pytest.raises(WeatherLookupError, match='查無 文山區 的天氣資料'):
            await fetch_district_weather('文山區', 'test_key')


@pytest.mark.asyncio
async def test_fetch_district_weather_logs_diagnostic_on_invalid_format():
    mock_response = {'success': 'false', 'result': {'resource_id': 'F-D0047-089'}}

    with (
        patch('weather.cwa.httpx.AsyncClient') as mock_client,
        patch('weather.cwa.logger') as mock_logger,
    ):
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=AsyncMock(
                status_code=200,
                json=lambda: mock_response,
                text='{"success":"false"}',
                raise_for_status=lambda: None,
            )
        )
        with pytest.raises(WeatherLookupError, match='中央氣象署天氣資料格式異常'):
            await fetch_district_weather('文山區', 'test_key')

    mock_logger.error.assert_called_once()
    error_call = mock_logger.error.call_args
    assert error_call.args[0] == 'Unexpected CWA response format for %s (status=%s): %s'
    assert error_call.args[1] == '文山區'
    assert error_call.args[2] == 200
    assert '{"success":"false"}' in error_call.args[3]
