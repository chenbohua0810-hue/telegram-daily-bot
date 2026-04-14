import logging
from dataclasses import dataclass

import httpx

CWA_BASE_URL = 'https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-D0047-061'
logger = logging.getLogger(__name__)


class WeatherLookupError(Exception):
    pass


@dataclass(frozen=True)
class WeatherData:
    district: str
    description: str
    max_temp: int
    min_temp: int
    rain_prob: int


def _get_value(data: dict, *keys: str):
    for key in keys:
        if key in data:
            return data[key]
    return None


def _truncate_text(value: str, limit: int = 500) -> str:
    return value if len(value) <= limit else f'{value[:limit]}...'


def _normalize_location_name(value: str | None) -> str:
    if value is None:
        return ''
    return value.strip().replace('台', '臺')


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


def _extract_element(elements: list, name: str) -> str:
    for el in elements:
        element_name = _get_value(el, 'elementName', 'ElementName')
        if element_name == name:
            return _extract_element_payload_value(el, name)
    return 'N/A'


def _extract_temperature_series(elements: list) -> list[int]:
    for element in elements:
        element_name = _get_value(element, 'elementName', 'ElementName')
        if element_name != 'Temperature':
            continue

        times = _get_value(element, 'time', 'Time') or []
        temperatures = []
        for time_entry in times:
            element_values = _get_value(time_entry, 'elementValue', 'ElementValue') or []
            if not element_values:
                continue

            value_entry = element_values[0]
            value = _get_value(value_entry, 'Temperature', 'value')
            if value is None:
                continue

            try:
                temperatures.append(int(value))
            except (ValueError, TypeError):
                raise WeatherLookupError(f'溫度資料格式異常：{value}')
        return temperatures
    return []


def _extract_weather(elements: list) -> str:
    for name in ('Weather', 'Wx'):
        value = _extract_element(elements, name)
        if value != 'N/A':
            return value
    return 'N/A'


def _extract_int_element(
    elements: list,
    official_name: str,
    legacy_name: str,
    label: str,
) -> int:
    for name in (official_name, legacy_name):
        value = _extract_element(elements, name)
        if value != 'N/A':
            try:
                return int(value)
            except (ValueError, TypeError):
                raise WeatherLookupError(f'{label} 資料格式異常：{value}')
    raise WeatherLookupError(f'中央氣象署缺少 {label} 欄位。')


def _extract_temperature_bound(elements: list, label: str, bound: str) -> int:
    temperatures = _extract_temperature_series(elements)
    if not temperatures:
        raise WeatherLookupError(f'中央氣象署缺少 {label} 欄位。')
    return max(temperatures) if bound == 'max' else min(temperatures)


def _get_locations(data: dict) -> list:
    records = _get_value(data, 'records', 'Records') or {}
    locations_groups = _get_value(records, 'locations', 'Locations') or []
    if isinstance(locations_groups, dict):
        locations_groups = [locations_groups]
    if not locations_groups:
        return []

    all_locations = []
    for group in locations_groups:
        locations = _get_value(group, 'location', 'Location') or []
        if isinstance(locations, dict):
            all_locations.append(locations)
            continue
        all_locations.extend(locations)
    return all_locations


def _get_location_group_names(data: dict) -> list[str]:
    records = _get_value(data, 'records', 'Records') or {}
    locations_groups = _get_value(records, 'locations', 'Locations') or []
    if isinstance(locations_groups, dict):
        locations_groups = [locations_groups]

    group_names = []
    for group in locations_groups:
        group_name = _get_value(group, 'locationsName', 'LocationsName')
        if group_name:
            group_names.append(group_name)
    return group_names


async def fetch_district_weather(district: str, api_key: str) -> WeatherData:
    params = {
        'Authorization': api_key,
        'format': 'JSON',
        'locationName': district,
        'elementName': 'Wx,MaxT,MinT,PoP12h,Temperature',
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(CWA_BASE_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    records = _get_value(data, 'records', 'Records')
    if records is None:
        logger.error(
            'Unexpected CWA response format for %s (status=%s): %s',
            district,
            resp.status_code,
            _truncate_text(resp.text),
        )
        raise WeatherLookupError('中央氣象署天氣資料格式異常。')

    locations = _get_locations(data)
    if not locations:
        raise WeatherLookupError(f'查無 {district} 的天氣資料。')

    normalized_district = _normalize_location_name(district)
    location = next(
        (
            item for item in locations
            if _normalize_location_name(_get_value(item, 'locationName', 'LocationName'))
            == normalized_district
        ),
        None,
    )
    if location is None:
        available_locations = [
            _get_value(item, 'locationName', 'LocationName') for item in locations
        ]
        logger.warning(
            'CWA location lookup miss for %s. Available groups=%s locations=%s',
            district,
            _get_location_group_names(data),
            available_locations,
        )
        raise WeatherLookupError(f'查無 {district} 的天氣資料。')

    elements = _get_value(location, 'weatherElement', 'WeatherElement') or []

    return WeatherData(
        district=district,
        description=_extract_weather(elements),
        max_temp=(
            _extract_element(elements, 'MaxTemperature') != 'N/A'
            or _extract_element(elements, 'MaxT') != 'N/A'
        )
        and _extract_int_element(elements, 'MaxTemperature', 'MaxT', '最高溫')
        or _extract_temperature_bound(elements, '最高溫', 'max'),
        min_temp=(
            _extract_element(elements, 'MinTemperature') != 'N/A'
            or _extract_element(elements, 'MinT') != 'N/A'
        )
        and _extract_int_element(elements, 'MinTemperature', 'MinT', '最低溫')
        or _extract_temperature_bound(elements, '最低溫', 'min'),
        rain_prob=_extract_int_element(
            elements, 'ProbabilityOfPrecipitation', 'PoP12h', '降雨機率'
        ),
    )
