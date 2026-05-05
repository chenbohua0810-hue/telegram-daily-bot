from pathlib import Path

from kronos_trading_bot.config import load_project_config, load_yaml_config


def test_default_configs_load_with_paper_mode_and_live_disabled():
    # Arrange
    project_root = Path(__file__).resolve().parents[1]

    # Act
    config = load_project_config(project_root / "configs")

    # Assert
    assert config.risk_policy["mode"] == "paper"
    assert config.risk_policy["allow_live_trading"] is False
    assert config.app["execution_mode"] == "paper"
    assert config.symbols["symbols"] == ["BTC/USDT", "ETH/USDT"]


def test_configs_contain_no_secret_like_keys():
    # Arrange
    project_root = Path(__file__).resolve().parents[1]

    # Act
    config = load_project_config(project_root / "configs")

    # Assert
    assert config.secret_like_keys == []


def test_load_yaml_config_returns_mapping():
    # Arrange
    path = Path(__file__).resolve().parents[1] / "configs" / "risk_policy.yaml"

    # Act
    data = load_yaml_config(path)

    # Assert
    assert data["starting_balance_usdt"] == 10000
