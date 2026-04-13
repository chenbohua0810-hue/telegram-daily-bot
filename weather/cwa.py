from dataclasses import dataclass
import logging

import httpx

CWA_BASE_URL = 'https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-D0047-093'
logger = logging.getLogger(__name__)


class WeatherLookupError(Exception):
    pass


@dataclass
class WeatherData:
    district: str
    description: str
    max_temp: int
    min_temp: int
    rain_prob: int


def _extract_element(elements: list, name: str) -> str:
    for el in elements:
        element_name = _get_value(el, 'elementName', 'ElementName')
        if element_name == name:
            return _extract_element_payload_value(el, name)
    return 'N/A'


def _truncate_text(value: str, limit: int = 500) -> str:
    return value if len(value) <= limit else f'{value[:limit]}...'


def _get_value(data: dict, *keys: str):
    for key in keys:
        if key in data:
            return data[key]
    return None


def _extract_element_payload_value(element: dict, element_name: str) -> str:
    times = _get_value(element, 'time', 'Time') or []
    if not times:
        return 'N/A'

    element_values = _get_value(times[0], 'elementValue', 'ElementValue') or []
    if not element_values:
        return 'N/A'

    value_entry = element_values[0]
    field_candidates = {
        'Weather': ['Weather', 'value'],
        'Wx': ['value'],
        'MaxTemperature': ['MaxTemperature', 'value'],
        'MaxT': ['value'],
        'MinTemperature': ['MinTemperature', 'value'],
        'MinT': ['value'],
        'ProbabilityOfPrecipitation': ['ProbabilityOfPrecipitation', 'value'],
        'PoP12h': ['value'],
    }
    for field_name in field_candidates.get(element_name, ['value']):
        value = _get_value(value_entry, field_name)
        if value is not None:
            return value
    return 'N/A'


def _extract_weather(elements: list) -> str:
    for name in ('Weather', 'Wx'):
        value = _extract_element(elements, name)
        if value != 'N/A':
            return value
    return 'N/A'


def _extract_temperature(elements: list, official_name: str, legacy_name: str) -> int:
    for name in (official_name, legacy_name):
        value = _extract_element(elements, name)
        if value != 'N/A':
            return int(value)
    raise WeatherLookupError(f'中央氣象署缺少 {official_name} 欄位。')


def _get_locations(data: dict) -> list:
    records = _get_value(data, 'records', 'Records') or {}
    locations_groups = _get_value(records, 'locations', 'Locations') or []
    if isinstance(locations_groups, dict):
        locations_groups = [locations_groups]
    if not locations_groups:
        return []

    first_group = locations_groups[0]
    locations = _get_value(first_group, 'location', 'Location') or []
    if isinstance(locations, dict):
        return [locations]
    return locations


async def fetch_district_weather(district: str, api_key: str) -> WeatherData:
    params = {
        'Authorization': api_key,
        'locationName': district,
        'elementName': 'Weather,MaxTemperature,MinTemperature,ProbabilityOfPrecipitation',
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(CWA_BASE_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    records = _get_value(data, 'records', 'Records')
    response_text = str(getattr(resp, 'text', ''))
    locations = _get_locations(data)
    if records is None:
        logger.error(
            'Unexpected CWA response format for %s (status=%s): %s',
            district,
            resp.status_code,
            _truncate_text(response_text),
        )
        raise WeatherLookupError('中央氣象署天氣資料格式異常。')
    if not locations:
        raise WeatherLookupError(f'查無 {district} 的天氣資料。')

    location = next(
        (
            item for item in locations
            if _get_value(item, 'locationName', 'LocationName') == district
        ),
        None,
    )
    if location is None:
        raise WeatherLookupError(f'查無 {district} 的天氣資料。')

    elements = _get_value(location, 'weatherElement', 'WeatherElement') or []

    return WeatherData(
        district=district,
        description=_extract_weather(elements),
        max_temp=_extract_temperature(elements, 'MaxTemperature', 'MaxT'),
        min_temp=_extract_temperature(elements, 'MinTemperature', 'MinT'),
        rain_prob=_extract_temperature(
            elements,
            'ProbabilityOfPrecipitation',
            'PoP12h',
        ),
    )
