from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class ForecastAdapter(Protocol):
    model_name: str
    tokenizer_name: str

    def predict(self, candles: list[dict[str, Any]], pred_len: int) -> list[dict[str, Any]]:
        pass


@dataclass(frozen=True)
class ForecastResult:
    model_name: str
    tokenizer_name: str
    pred_len: int
    predictions: list[dict[str, Any]]


def run_forecast(
    forecaster: ForecastAdapter,
    candles: list[dict[str, Any]],
    *,
    pred_len: int,
) -> ForecastResult:
    predictions = forecaster.predict(candles, pred_len)
    return ForecastResult(
        model_name=forecaster.model_name,
        tokenizer_name=forecaster.tokenizer_name,
        pred_len=pred_len,
        predictions=predictions,
    )
