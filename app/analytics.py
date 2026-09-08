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
from types import SimpleNamespace


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


def _benchmark_volatility(benchmark_values: Mapping[date, float], trade_date: date, window: int = 20) -> float | None:
    dates = sorted(day for day in benchmark_values if day <= trade_date)
    if len(dates) <= window:
        return None
    returns = []
    for current, previous in zip(dates[-window:], dates[-window - 1 : -1]):
        if benchmark_values[previous]:
            returns.append(benchmark_values[current] / benchmark_values[previous] - 1.0)
    return pstdev(returns) if len(returns) >= 10 else None


def _broker_flow_map(rows: Iterable[Any]) -> dict[tuple[str, date], float]:
    result: defaultdict[tuple[str, date], float] = defaultdict(float)
    for row in rows:
        symbol = str(getattr(row, "symbol", "")).upper()
        trade_date = getattr(row, "trade_date", None)
        value = _number(getattr(row, "net_value", None))
        if symbol and trade_date is not None and value is not None:
            result[(symbol, trade_date)] += value
    return dict(result)


def _ema(values: list[float | None], index: int, window: int) -> float | None:
    """Trading-session EMA that returns NULL until a complete seed exists."""

    if index < window - 1:
        return None
    sample = values[: index + 1]
    if any(value is None for value in sample[:window]):
        return None
    result = sum(value for value in sample[:window] if value is not None) / window
    alpha = 2.0 / (window + 1.0)
    for value in sample[window:]:
        if value is not None:
            result = alpha * value + (1.0 - alpha) * result
    return result


def _rsi(values: list[float | None], index: int, window: int = 14) -> float | None:
    if index < window or any(value is None for value in values[index - window : index + 1]):
        return None
    gains = 0.0
    losses = 0.0
    for current, previous in zip(values[index - window + 1 : index + 1], values[index - window : index]):
        change = (current or 0.0) - (previous or 0.0)
        if change >= 0:
            gains += change
        else:
            losses -= change
    if losses == 0:
        return 100.0
    relative_strength = (gains / window) / (losses / window)
    return 100.0 - (100.0 / (1.0 + relative_strength))


def _atr(rows: list[Any], index: int, window: int = 14) -> float | None:
    if index < window or index >= len(rows):
        return None
    ranges: list[float] = []
    for position in range(index - window + 1, index + 1):
        high = _number(getattr(rows[position], "high", None))
        low = _number(getattr(rows[position], "low", None))
        close_previous = _number(getattr(rows[position - 1], "close", None)) if position else None
        if high is None or low is None:
            return None
        ranges.append(max(high - low, abs(high - close_previous) if close_previous is not None else 0.0, abs(low - close_previous) if close_previous is not None else 0.0))
    return sum(ranges) / window if len(ranges) == window else None


def _beta_correlation(asset_returns: list[float | None], benchmark_values: Mapping[date, float], dates: list[date], index: int, window: int = 20) -> tuple[float | None, float | None]:
    if index < window:
        return None, None
    asset: list[float] = []
    market: list[float] = []
    for position in range(index - window + 1, index + 1):
        current = asset_returns[position]
        previous_date = dates[position - 1] if position else None
        current_date = dates[position]
        if current is None or previous_date is None or previous_date not in benchmark_values or current_date not in benchmark_values:
            continue
        market_previous = benchmark_values[previous_date]
        market_current = benchmark_values[current_date]
        if market_previous == 0:
            continue
        asset.append(current)
        market.append(market_current / market_previous - 1.0)
    if len(asset) < max(10, window // 2):
        return None, None
    mean_asset = sum(asset) / len(asset)
    mean_market = sum(market) / len(market)
    covariance = sum((a - mean_asset) * (m - mean_market) for a, m in zip(asset, market))
    variance = sum((m - mean_market) ** 2 for m in market)
    if variance == 0:
        return None, None
    beta = covariance / variance
    asset_std = math.sqrt(sum((a - mean_asset) ** 2 for a in asset))
    market_std = math.sqrt(variance)
    correlation = covariance / (asset_std * market_std) if asset_std and market_std else None
    return beta, correlation


def _broker_metrics(rows: Iterable[Any], symbol: str, trade_date: date) -> dict[str, float | None]:
    all_rows = [row for row in rows if str(getattr(row, "symbol", "")).upper() == symbol and getattr(row, "trade_date", None) <= trade_date]
    selected = [row for row in all_rows if getattr(row, "trade_date", None) == trade_date]
    if not selected:
        return {"broker_net_value": None, "broker_concentration": None, "broker_persistence": None}
    values = [max(0.0, _number(getattr(row, "buy_value", None)) or 0.0) for row in selected]
    total = sum(values)
    concentration = sum((value / total) ** 2 for value in values) if total else None
    net = sum((_number(getattr(row, "net_value", None)) or 0.0) for row in selected)
    daily_net: defaultdict[date, float] = defaultdict(float)
    for row in all_rows:
        daily_net[getattr(row, "trade_date")] += _number(getattr(row, "net_value", None)) or 0.0
    recent = [value for _, value in sorted(daily_net.items())[-5:]]
    persistence = sum(1.0 if value > 0 else -1.0 if value < 0 else 0.0 for value in recent) / len(recent) if recent else None
    return {"broker_net_value": net, "broker_concentration": concentration, "broker_persistence": persistence}


def _foreign_persistence(rows: Iterable[Any], symbol: str, trade_date: date, window: int = 5) -> float | None:
    values: list[float] = []
    for row in rows:
        if str(getattr(row, "symbol", "")).upper() != symbol or getattr(row, "trade_date", None) > trade_date:
            continue
        net = _number(getattr(row, "foreign_net_value", None))
        if net is None:
            buy = _number(getattr(row, "foreign_buy_volume", None))
            sell = _number(getattr(row, "foreign_sell_volume", None))
            net = buy - sell if buy is not None and sell is not None else None
        if net is not None:
            values.append(net)
    if not values:
        return None
    selected = values[-window:]
    return sum(1.0 if value > 0 else -1.0 if value < 0 else 0.0 for value in selected) / len(selected)


def analyze_ohlcv(
    rows: Iterable[Any],
    *,
    from_date: date | None = None,
    to_date: date | None = None,
    benchmark_rows: Iterable[Any] = (),
    foreign_rows: Iterable[Any] = (),
    broker_rows: Iterable[Any] = (),
    stock_summary_rows: Iterable[Any] = (),
    adjusted_rows: Iterable[Any] = (),
    event_rows: Iterable[Any] = (),
    news_rows: Iterable[Any] = (),
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
    benchmark_dates = sorted(benchmark_values)
    # A 20-session benchmark return needs the current close plus the close
    # from 20 earlier trading sessions. Keep this requirement explicit in the
    # result so the UI can explain why the combined probability is unavailable.
    benchmark_required_observations = 21
    stock_summary_map = {
        (str(getattr(row, "symbol", "")).upper(), getattr(row, "trade_date", None)): row
        for row in stock_summary_rows
    }
    adjusted_map = {
        (str(getattr(row, "symbol", "")).upper(), getattr(row, "trade_date", None)): row
        for row in adjusted_rows
    }
    event_map: defaultdict[tuple[str, date], int] = defaultdict(int)
    for row in event_rows:
        symbol = str(getattr(row, "symbol", "") or "").upper()
        event_date = getattr(row, "event_date", None)
        if event_date is not None:
            event_map[(symbol, event_date)] += 1
    news_map: dict[str, list[Any]] = defaultdict(list)
    for row in news_rows:
        symbol = str(getattr(row, "symbol", "") or "").upper()
        if symbol:
            news_map[symbol].append(row)
    foreign_map = {
        (str(getattr(row, "symbol", "")).upper(), getattr(row, "trade_date", None)): row
        for row in foreign_rows
    }
    broker_flow = _broker_flow_map(broker_rows)
    result: list[dict[str, Any]] = []

    for symbol, raw_symbol_rows in sorted(grouped.items()):
        raw_symbol_rows = sorted(raw_symbol_rows, key=lambda item: getattr(item, "trade_date"))
        # Technical indicators can use the materialized adjusted series when
        # corporate-action terms are available.  The raw OHLCV fact table is
        # still preserved and returned separately by the API/export routes.
        symbol_rows: list[Any] = []
        adjusted_flags: list[bool] = []
        for raw_row in raw_symbol_rows:
            adjusted = adjusted_map.get((symbol, getattr(raw_row, "trade_date", None)))
            if adjusted is None:
                symbol_rows.append(raw_row)
                adjusted_flags.append(False)
                continue
            symbol_rows.append(
                SimpleNamespace(
                    symbol=symbol,
                    trade_date=getattr(raw_row, "trade_date"),
                    open=getattr(adjusted, "adjusted_open", None),
                    high=getattr(adjusted, "adjusted_high", None),
                    low=getattr(adjusted, "adjusted_low", None),
                    close=getattr(adjusted, "adjusted_close", None),
                    volume=getattr(adjusted, "adjusted_volume", None),
                )
            )
            adjusted_flags.append(True)
        row_dates = [getattr(item, "trade_date") for item in symbol_rows]
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
            ema5 = _ema(closes, index, 5)
            ema10 = _ema(closes, index, 10)
            ema20 = _ema(closes, index, 20)
            ema50 = _ema(closes, index, 50)
            rsi14 = _rsi(closes, index)
            atr14 = _atr(symbol_rows, index)
            return5 = _period_return(closes, index, 5)
            return10 = _period_return(closes, index, 10)
            return20 = _period_return(closes, index, 20)
            average_volume20 = _rolling_average(volumes, index, 20)
            volume = volumes[index]
            volume_ratio = volume / average_volume20 if volume is not None and average_volume20 else None
            volatility_values = [value for value in daily_returns[max(0, index - 19) : index + 1] if value is not None]
            volatility20 = pstdev(volatility_values) if len(volatility_values) >= 10 else None
            close_window = [value for value in closes[max(0, index - 19) : index + 1] if value is not None]
            mean_reversion_z20 = None
            if len(close_window) == 20:
                average = sum(close_window) / len(close_window)
                deviation = pstdev(close_window)
                mean_reversion_z20 = (close - average) / deviation if close is not None and deviation else None
            mean_reversion_signal = (
                _clamp(-(mean_reversion_z20 or 0.0) / 2.0)
                if mean_reversion_z20 is not None
                else None
            )

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
            mean_reversion_score = (
                50.0 + 50.0 * mean_reversion_signal
                if mean_reversion_signal is not None
                else None
            )
            ensemble_score = (
                0.75 * simons_score + 0.25 * mean_reversion_score
                if simons_score is not None and mean_reversion_score is not None
                else simons_score
            )

            benchmark_observation_count = sum(
                1 for benchmark_date in benchmark_dates if benchmark_date <= trade_date
            )
            benchmark_return20 = _benchmark_return(benchmark_values, trade_date, 20)
            benchmark_volatility20 = _benchmark_volatility(benchmark_values, trade_date)
            if benchmark_return20 is None:
                market_regime = "Belum cukup data benchmark"
            elif benchmark_return20 >= 0.05:
                market_regime = "Bullish"
            elif benchmark_return20 <= -0.05:
                market_regime = "Bearish"
            else:
                market_regime = "Sideways"
            beta20, correlation20 = _beta_correlation(daily_returns, benchmark_values, row_dates, index)
            excess_return20 = return20 - benchmark_return20 if return20 is not None and benchmark_return20 is not None else None
            residual_momentum20 = excess_return20 - ((beta20 or 1.0) * (benchmark_return20 or 0.0)) if excess_return20 is not None else None
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
            benchmark_status = (
                "Benchmark IHSG siap untuk model gabungan"
                if benchmark_observation_count >= benchmark_required_observations
                else (
                    "Benchmark IHSG belum cukup "
                    f"({benchmark_observation_count}/{benchmark_required_observations} hari bursa)"
                )
            )

            foreign = foreign_map.get((symbol, trade_date))
            foreign_net = _number(getattr(foreign, "foreign_net_value", None)) if foreign else None
            if foreign_net is None and foreign:
                buy_volume = _number(getattr(foreign, "foreign_buy_volume", None))
                sell_volume = _number(getattr(foreign, "foreign_sell_volume", None))
                foreign_net = buy_volume - sell_volume if buy_volume is not None and sell_volume is not None else None
            broker_metrics = _broker_metrics(broker_rows, symbol, trade_date)
            broker_net = broker_flow.get((symbol, trade_date), broker_metrics["broker_net_value"])
            summary = stock_summary_map.get((symbol, trade_date))
            trading_value = _number(getattr(summary, "value", None)) if summary else None
            frequency = _number(getattr(summary, "frequency", None)) if summary else None
            tradeable_shares = _number(getattr(summary, "tradeable_shares", None)) if summary else None
            vwap = trading_value / volume if trading_value is not None and volume else None
            turnover_ratio = volume / tradeable_shares if volume is not None and tradeable_shares else None
            listed_shares = _number(getattr(summary, "listed_shares", None)) if summary else None
            market_cap = close * listed_shares if close is not None and listed_shares else None
            free_float_shares = tradeable_shares
            free_float_percentage = (
                free_float_shares / listed_shares
                if free_float_shares is not None and listed_shares
                else None
            )
            free_float_market_cap = (
                close * free_float_shares
                if close is not None and free_float_shares
                else None
            )
            foreign_sign = (
                1.0 if foreign_net > 0 else -1.0 if foreign_net < 0 else 0.0
            ) if foreign_net is not None else None
            broker_sign = (
                1.0 if broker_net > 0 else -1.0 if broker_net < 0 else 0.0
            ) if broker_net is not None else None
            flow_signals = [value for value in (foreign_sign, broker_sign) if value is not None]
            flow_confirmation = sum(flow_signals) / len(flow_signals) if flow_signals else None
            latest_news = sorted(
                news_map.get(symbol, []),
                key=lambda item: str(getattr(item, "published_at", "")),
            )[-1:]
            sentiment_score = (
                _number(getattr(latest_news[0], "sentiment_score", None))
                if latest_news
                else None
            )
            event_count = event_map.get((symbol, trade_date), 0)
            probability_for_rule = p_final if p_final is not None else p_model
            entry_signal = "Belum cukup data"
            if ensemble_score is not None:
                if probability_for_rule is not None and ensemble_score >= 65 and probability_for_rule >= 0.55:
                    entry_signal = "Kandidat entry riset"
                elif ensemble_score <= 35 or (probability_for_rule is not None and probability_for_rule <= 0.45):
                    entry_signal = "Kurangi / hindari"
                else:
                    entry_signal = "Pantau"
            stop_price = close - 2.0 * atr14 if close is not None and atr14 is not None else None
            take_profit_price = close + 3.0 * atr14 if close is not None and atr14 is not None else None
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
                    "ema5": ema5,
                    "ema10": ema10,
                    "ema20": ema20,
                    "ema50": ema50,
                    "rsi14": rsi14,
                    "atr14": atr14,
                    "return5": return5,
                    "return10": return10,
                    "return20": return20,
                    "volume_ratio20": volume_ratio,
                    "volatility20": volatility20,
                    "mean_reversion_z20": mean_reversion_z20,
                    "mean_reversion_signal": mean_reversion_signal,
                    "mean_reversion_score": mean_reversion_score,
                    "ensemble_score": ensemble_score,
                    "market_regime": market_regime,
                    "benchmark_observation_count": benchmark_observation_count,
                    "benchmark_required_observations": benchmark_required_observations,
                    "benchmark_status": benchmark_status,
                    "breakout_20": bool(close is not None and index >= 20 and all(_number(getattr(item, "high", None)) is not None for item in symbol_rows[index - 20 : index]) and close > max(_number(getattr(item, "high", 0)) or 0 for item in symbol_rows[index - 20 : index])),
                    "benchmark_return20": benchmark_return20,
                    "benchmark_volatility20": benchmark_volatility20,
                    "excess_return20": excess_return20,
                    "beta20": beta20,
                    "correlation20": correlation20,
                    "residual_momentum20": residual_momentum20,
                    "trading_value": trading_value,
                    "frequency": frequency,
                    "vwap": vwap,
                    "market_cap": market_cap,
                    "free_float_shares": free_float_shares,
                    "free_float_percentage": free_float_percentage,
                    "free_float_market_cap": free_float_market_cap,
                    "tradeable_shares": tradeable_shares,
                    "turnover_ratio": turnover_ratio,
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
                    "flow_confirmation": flow_confirmation,
                    "broker_concentration": broker_metrics["broker_concentration"],
                    "broker_persistence": broker_metrics["broker_persistence"],
                    "foreign_persistence": _foreign_persistence(foreign_rows, symbol, trade_date),
                    "event_count": event_count,
                    "event_risk": bool(event_count),
                    "sentiment_score": sentiment_score,
                    "stop_price": stop_price,
                    "take_profit_price": take_profit_price,
                    "entry_signal": entry_signal,
                    "price_source": "adjusted" if adjusted_flags[index] else "raw",
                    "data_status": "ready" if data_ready else "insufficient-history",
                    "model_version": "research-baseline-v1",
                }
            )
    # Cross-sectional relative-strength rank is computed only among the
    # symbols present in this request, so it is explicit about its universe.
    by_date: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in result:
        by_date[item["trade_date"]].append(item)
    for items in by_date.values():
        ranked = sorted(items, key=lambda item: item.get("return20") if item.get("return20") is not None else -float("inf"), reverse=True)
        denominator = max(1, len(ranked) - 1)
        for rank, item in enumerate(ranked):
            item["relative_strength_rank"] = 1.0 - (rank / denominator) if item.get("return20") is not None else None
    return result

