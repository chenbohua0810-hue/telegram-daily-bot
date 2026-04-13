from dataclasses import dataclass

import httpx

CWA_BASE_URL = 'https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-D0047-089'


@dataclass
class WeatherData:
    district: str
    description: str
    max_temp: int
    min_temp: int
    rain_prob: int


def _extract_element(elements: list, name: str) -> str:
    for el in elements:
        if el['elementName'] == name:
            return el['time'][0]['elementValue'][0]['value']
    return 'N/A'


async def fetch_district_weather(district: str, api_key: str) -> WeatherData:
    params = {
        'Authorization': api_key,
        'locationName': district,
        'elementName': 'Wx,MaxT,MinT,PoP12h',
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(CWA_BASE_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    location = data['records']['locations'][0]['location'][0]
    elements = location['weatherElement']

    return WeatherData(
        district=district,
        description=_extract_element(elements, 'Wx'),
        max_temp=int(_extract_element(elements, 'MaxT')),
        min_temp=int(_extract_element(elements, 'MinT')),
        rain_prob=int(_extract_element(elements, 'PoP12h')),
    )
