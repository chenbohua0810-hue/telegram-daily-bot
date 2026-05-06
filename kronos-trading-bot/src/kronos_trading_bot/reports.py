from __future__ import annotations

from pathlib import Path
from typing import Any


def write_cycle_report(
    report_dir: Path,
    *,
    symbol: str,
    status: str,
    live_orders_attempted: int,
    details: dict[str, Any],
) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "latest_report.md"
    lines = [
        f"# Kronos Paper Cycle Report: {symbol}",
        "",
        f"status: {status}",
        f"live_orders_attempted: {live_orders_attempted}",
    ]
    for key in sorted(details):
        lines.append(f"{key}: {_format_report_value(details[key])}")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def _format_report_value(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)
