import importlib
import sys

import pytest


def reload_config(monkeypatch: pytest.MonkeyPatch):
    sys.modules.pop('config', None)
    return importlib.import_module('config')


def test_config_accepts_single_weather_district_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'token')
    monkeypatch.setenv('TELEGRAM_GROUP_ID', '')
    monkeypatch.setenv('CWA_API_KEY', '')
    monkeypatch.setenv('GEMINI_API_KEY', '')
    monkeypatch.setenv('WEATHER_DISTRICTS', '')
    monkeypatch.setenv('WEATHER_DISTRICT', '大安區')

    config = reload_config(monkeypatch)

    assert config.WEATHER_DISTRICTS == ['大安區']


def test_config_allows_optional_runtime_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'token')
    monkeypatch.setenv('TELEGRAM_GROUP_ID', '')
    monkeypatch.setenv('CWA_API_KEY', '')
    monkeypatch.setenv('GEMINI_API_KEY', '')
    monkeypatch.setenv('WEATHER_DISTRICT', '')
    monkeypatch.setenv('WEATHER_DISTRICTS', '')

    config = reload_config(monkeypatch)

    assert config.TELEGRAM_GROUP_ID is None
    assert config.CWA_API_KEY is None
    assert config.GEMINI_API_KEY is None
    assert config.WEATHER_DISTRICTS == ['文山區', '小港區']
