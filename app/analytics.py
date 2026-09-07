"""Deterministic, explainable research indicators for the IDX dashboard.

The module deliberately calls the two research modes *inspired* approaches.
It does not claim to reproduce any proprietary Jim Simons system or Bill
Benter's horse-racing implementation.  Scores are useful for exploration and
backtesting only until they are calibrated on a much longer, clean dataset.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import date
from statistics import pstdev
from typing import Any


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _clamp(value: float, lower: float = -1.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _sigmoid(value: float) -> float:
    value = max(-35.0, min(35.0, value))
    return 1.0 / (1.0 + math.exp(-value))


def _logit(value: float) -> float:
    value = max(0.001, min(0.999, value))
    return math.log(value / (1.0 - value))


def _rolling_average(values: list[float | None], index: int, window: int) -> float | None:
    sample = [value for value in values[max(0, index - window + 1) : index + 1] if value is not None]
    if len(sample) != window:
        return None
    return sum(sample) / window


def _period_return(values: list[float | None], index: int, window: int) -> float | None:
    current = values[index]
    previous_index = index - window
    previous = values[previous_index] if previous_index >= 0 else None
    if current is None or previous in (None, 0):
        return None
    return current / previous - 1.0


def _label(score: float | None) -> str:
    if score is None:
        return "Belum cukup data"
    if score >= 80:
        return "Kuat positif"
    if score >= 65:
        return "Positif"
    if score >= 35:
        return "Netral"
    if score >= 20:
        return "Negatif"
    return "Kuat negatif"


def _date_map(rows: Iterable[Any], value_name: str = "close") -> dict[date, float]:
    result: dict[date, float] = {}
    for row in rows:
        trade_date = getattr(row, "trade_date", None)
        value = _number(getattr(row, value_name, None))
        if trade_date is not None and value is not None:
            result[trade_date] = value
    return result


def _benchmark_return(
    benchmark_values: Mapping[date, float], trade_date: date, window: int
) -> float | None:
    dates = sorted(day for day in benchmark_values if day <= trade_date)
    if len(dates) <= window:
        return None
    current_date = dates[-1]
    previous_date = dates[-window - 1]
    previous = benchmark_values[previous_date]
    if previous == 0:
        return None
    return benchmark_values[current_date] / previous - 1.0


def _broker_flow_map(rows: Iterable[Any]) -> dict[tuple[str, date], float]:
    result: defaultdict[tuple[str, date], float] = defaultdict(float)
    for row in rows:
        symbol = str(getattr(row, "symbol", "")).upper()
        trade_date = getattr(row, "trade_date", None)
        value = _number(getattr(row, "net_value", None))
        if symbol and trade_date is not None and value is not None:
            result[(symbol, trade_date)] += value
    return dict(result)


def analyze_ohlcv(
    rows: Iterable[Any],
    *,
    from_date: date | None = None,
    to_date: date | None = None,
    benchmark_rows: Iterable[Any] = (),
    foreign_rows: Iterable[Any] = (),
    broker_rows: Iterable[Any] = (),
) -> list[dict[str, Any]]:
    """Calculate MA5/10/20/50 and explainable research fields.

    Rows before ``from_date`` are intentionally accepted so the first visible
    row can still have a valid MA50.  Only the requested output date range is
    returned.
    """

    grouped: defaultdict[str, list[Any]] = defaultdict(list)
    for row in rows:
        grouped[str(getattr(row, "symbol", "")).upper()].append(row)
    benchmark_values = _date_map(benchmark_rows)
    foreign_map = {
        (str(getattr(row, "symbol", "")).upper(), getattr(row, "trade_date", None)): row
        for row in foreign_rows
    }
    broker_flow = _broker_flow_map(broker_rows)
    result: list[dict[str, Any]] = []

    for symbol, symbol_rows in sorted(grouped.items()):
        symbol_rows = sorted(symbol_rows, key=lambda item: getattr(item, "trade_date"))
        closes = [_number(getattr(row, "close", None)) for row in symbol_rows]
        volumes = [_number(getattr(row, "volume", None)) for row in symbol_rows]
        daily_returns: list[float | None] = [None]
        for index in range(1, len(closes)):
            current, previous = closes[index], closes[index - 1]
            daily_returns.append(current / previous - 1.0 if current is not None and previous else None)

        for index, row in enumerate(symbol_rows):
            trade_date = getattr(row, "trade_date")
            if from_date and trade_date < from_date:
                continue
            if to_date and trade_date > to_date:
                continue
            close = closes[index]
            ma5 = _rolling_average(closes, index, 5)
            ma10 = _rolling_average(closes, index, 10)
            ma20 = _rolling_average(closes, index, 20)
            ma50 = _rolling_average(closes, index, 50)
            return5 = _period_return(closes, index, 5)
            return10 = _period_return(closes, index, 10)
            return20 = _period_return(closes, index, 20)
            average_volume20 = _rolling_average(volumes, index, 20)
            volume = volumes[index]
            volume_ratio = volume / average_volume20 if volume is not None and average_volume20 else None
            volatility_values = [value for value in daily_returns[max(0, index - 19) : index + 1] if value is not None]
            volatility20 = pstdev(volatility_values) if len(volatility_values) >= 10 else None

            conditions: list[bool] = []
            if close is not None and ma5 is not None:
                conditions.append(close > ma5)
            if ma5 is not None and ma10 is not None:
                conditions.append(ma5 > ma10)
            if ma10 is not None and ma20 is not None:
                conditions.append(ma10 > ma20)
            if ma20 is not None and ma50 is not None:
                conditions.append(ma20 > ma50)
            trend_score = (sum(conditions) / 4.0 * 100.0) if len(conditions) == 4 else None
            trend_signal = ((sum(conditions) / 2.0) - 1.0) if len(conditions) == 4 else None
            momentum_signal = None
            if return5 is not None and return10 is not None and return20 is not None:
                momentum_signal = math.tanh(return5 * 8.0 + return10 * 5.0 + return20 * 3.0)
            volume_signal = _clamp((volume_ratio - 1.0) / 2.0) if volume_ratio is not None else 0.0
            risk_penalty = _clamp((volatility20 or 0.0) * 12.0, 0.0, 1.0)

            simons_score: float | None = None
            if trend_signal is not None and momentum_signal is not None:
                signal = (
                    0.50 * trend_signal
                    + 0.35 * momentum_signal
                    + 0.15 * volume_signal
                    - 0.10 * risk_penalty
                )
                simons_score = max(0.0, min(100.0, 50.0 + 50.0 * signal))

            benchmark_return20 = _benchmark_return(benchmark_values, trade_date, 20)
            p_model = _sigmoid((simons_score - 50.0) / 12.0) if simons_score is not None else None
            p_market = _sigmoid(math.tanh(benchmark_return20 * 8.0) * 2.0) if benchmark_return20 is not None else None
            p_final = None
            edge = None
            probability_status = "Belum cukup data teknikal"
            if p_model is not None and p_market is not None:
                p_final = _sigmoid(0.65 * _logit(p_model) + 0.35 * _logit(p_market))
                edge = p_final - p_market
                probability_status = "Baseline terkalibrasi dengan benchmark"
            elif p_model is not None:
                probability_status = "Benchmark diperlukan untuk model gabungan"

            foreign = foreign_map.get((symbol, trade_date))
            foreign_net = _number(getattr(foreign, "foreign_net_value", None)) if foreign else None
            broker_net = broker_flow.get((symbol, trade_date))
            if broker_net is None:
                broker_net = None
            data_ready = simons_score is not None
            result.append(
                {
                    "symbol": symbol,
                    "trade_date": trade_date.isoformat(),
                    "close": close,
                    "volume": int(volume) if volume is not None else None,
                    "ma5": ma5,
                    "ma10": ma10,
                    "ma20": ma20,
                    "ma50": ma50,
                    "return5": return5,
                    "return10": return10,
                    "return20": return20,
                    "volume_ratio20": volume_ratio,
                    "volatility20": volatility20,
                    "trend_score": trend_score,
                    "simons_score": simons_score,
                    "simons_label": _label(simons_score),
                    "p_model": p_model,
                    "p_market": p_market,
                    "p_final": p_final,
                    "edge": edge,
                    "probability_status": probability_status,
                    "foreign_net_value": foreign_net,
                    "broker_net_value": broker_net,
                    "data_status": "ready" if data_ready else "insufficient-history",
                    "model_version": "research-baseline-v1",
                }
            )
    return result

