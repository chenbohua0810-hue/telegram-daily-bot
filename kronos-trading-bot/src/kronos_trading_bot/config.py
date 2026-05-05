from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

SECRET_KEY_FRAGMENTS = (
    "api_key",
    "apikey",
    "secret",
    "password",
    "private_key",
    "wallet_seed",
    "access_token",
    "refresh_token",
    "bearer_token",
    "auth_token",
)


@dataclass(frozen=True)
class ProjectConfig:
    app: dict[str, Any]
    symbols: dict[str, Any]
    model: dict[str, Any]
    strategy: dict[str, Any]
    risk_policy: dict[str, Any]
    agents: dict[str, Any]
    paper_trading: dict[str, Any]
    secret_like_keys: list[str]


def load_yaml_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping in {path}")
    return data


def _find_secret_like_keys(value: Any, prefix: str = "") -> list[str]:
    if isinstance(value, dict):
        matches: list[str] = []
        for key, child in value.items():
            key_path = f"{prefix}.{key}" if prefix else str(key)
            normalized = str(key).lower()
            if any(fragment in normalized for fragment in SECRET_KEY_FRAGMENTS):
                matches.append(key_path)
            matches.extend(_find_secret_like_keys(child, key_path))
        return matches
    if isinstance(value, list):
        matches: list[str] = []
        for index, child in enumerate(value):
            matches.extend(_find_secret_like_keys(child, f"{prefix}[{index}]"))
        return matches
    return []


def load_project_config(config_dir: Path) -> ProjectConfig:
    app = load_yaml_config(config_dir / "app.yaml")
    symbols = load_yaml_config(config_dir / "symbols.yaml")
    model = load_yaml_config(config_dir / "model.yaml")
    strategy = load_yaml_config(config_dir / "strategy.yaml")
    risk_policy = load_yaml_config(config_dir / "risk_policy.yaml")
    agents = load_yaml_config(config_dir / "agents.yaml")
    paper_trading = load_yaml_config(config_dir / "paper_trading.yaml")
    combined = {
        "app": app,
        "symbols": symbols,
        "model": model,
        "strategy": strategy,
        "risk_policy": risk_policy,
        "agents": agents,
        "paper_trading": paper_trading,
    }
    return ProjectConfig(
        app=app,
        symbols=symbols,
        model=model,
        strategy=strategy,
        risk_policy=risk_policy,
        agents=agents,
        paper_trading=paper_trading,
        secret_like_keys=_find_secret_like_keys(combined),
    )
