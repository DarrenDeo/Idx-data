"""Leakage-aware, deterministic walk-forward evaluation helpers."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from statistics import mean, pstdev
from typing import Any, Iterable

from app.analytics import analyze_ohlcv


def _as_float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _max_drawdown(returns: list[float]) -> float:
    equity = 1.0
    peak = equity
    drawdown = 0.0
    for value in returns:
        equity *= 1.0 + value
        peak = max(peak, equity)
        drawdown = min(drawdown, equity / peak - 1.0)
    return drawdown


def summarize_backtest_outcomes(outcomes: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Summarize an already-filtered set of forward-return outcomes."""

    rows = list(outcomes)
    returns = [float(row["forward_return"]) for row in rows if row.get("forward_return") is not None]
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value <= 0]
    drawdown = _max_drawdown(returns) if returns else None
    profit_factor = sum(wins) / abs(sum(losses)) if losses and sum(losses) < 0 else None
    return {
        "signals": len(rows),
        "win_rate": len(wins) / len(returns) if returns else None,
        "average_forward_return": mean(returns) if returns else None,
        "average_win": mean(wins) if wins else None,
        "average_loss": mean(losses) if losses else None,
        "max_drawdown": drawdown,
        "return_volatility": pstdev(returns) if len(returns) > 1 else None,
        "profit_factor": profit_factor,
        "expected_drawdown": abs(drawdown) if drawdown is not None else None,
    }


def walk_forward_backtest(
    rows: Iterable[Any],
    *,
    benchmark_rows: Iterable[Any] = (),
    foreign_rows: Iterable[Any] = (),
    broker_rows: Iterable[Any] = (),
    stock_summary_rows: Iterable[Any] = (),
    adjusted_rows: Iterable[Any] = (),
    event_rows: Iterable[Any] = (),
    news_rows: Iterable[Any] = (),
    min_history: int = 50,
    horizon: int = 5,
    score_threshold: float = 65.0,
    probability_threshold: float = 0.55,
) -> dict[str, Any]:
    """Evaluate signals using only information available on each signal date.

    This is a research diagnostic, not a promise of tradable performance. The
    signal is calculated on date *t* and the return is measured on a later
    candle, so the target is not accidentally included in the feature window.
    """

    source = list(rows)
    analysis = analyze_ohlcv(
        source,
        benchmark_rows=benchmark_rows,
        foreign_rows=foreign_rows,
        broker_rows=broker_rows,
        stock_summary_rows=stock_summary_rows,
        adjusted_rows=adjusted_rows,
        event_rows=event_rows,
        news_rows=news_rows,
    )
    prices: defaultdict[str, list[tuple[date, float]]] = defaultdict(list)
    adjusted_map = {
        (str(getattr(row, "symbol", "")).upper(), getattr(row, "trade_date", None)): _as_float(
            getattr(row, "adjusted_close", None)
        )
        for row in adjusted_rows
    }
    for row in source:
        trade_date = getattr(row, "trade_date", None)
        symbol = str(getattr(row, "symbol", "")).upper()
        close = adjusted_map.get((symbol, trade_date)) or _as_float(getattr(row, "close", None))
        if close is not None and trade_date is not None:
            prices[symbol].append((trade_date, close))
    for values in prices.values():
        values.sort()

    outcomes: list[dict[str, Any]] = []
    for signal in analysis:
        if signal.get("simons_score") is None:
            continue
        probability = signal.get("p_final") or signal.get("p_model")
        if signal["simons_score"] < score_threshold or probability is None or probability < probability_threshold:
            continue
        symbol = signal["symbol"]
        signal_date = date.fromisoformat(signal["trade_date"])
        values = prices.get(symbol, [])
        if len(values) < min_history:
            continue
        positions = [index for index, (day, _) in enumerate(values) if day == signal_date]
        if not positions or positions[0] + horizon >= len(values):
            continue
        start_price = values[positions[0]][1]
        end_price = values[positions[0] + horizon][1]
        if start_price <= 0:
            continue
        outcomes.append({"symbol": symbol, "signal_date": signal["trade_date"], "horizon": horizon, "forward_return": end_price / start_price - 1.0, "score": signal["simons_score"], "probability": probability})

    metrics = summarize_backtest_outcomes(outcomes)
    return {
        "status": "ready" if outcomes else "insufficient-history",
        "model_version": "research-baseline-v1",
        "parameters": {"min_history": min_history, "horizon": horizon, "score_threshold": score_threshold, "probability_threshold": probability_threshold},
        **metrics,
        "rows": outcomes,
        "warning": "Hasil historis bukan jaminan dan belum memasukkan biaya, slippage, suspensi, atau kapasitas pasar.",
    }


def volatility_position_size(
    *,
    capital: float,
    risk_fraction: float,
    atr: float | None,
    stop_multiple: float = 2.0,
    price: float | None = None,
) -> dict[str, float | None]:
    """Return a transparent ATR-based position-size suggestion."""

    if capital <= 0 or risk_fraction <= 0 or atr is None or atr <= 0 or price is None or price <= 0:
        return {"shares": None, "notional": None, "stop_distance": None, "status": "insufficient-data"}
    stop_distance = atr * stop_multiple
    shares = int((capital * risk_fraction) / stop_distance)
    return {"shares": float(max(0, shares)), "notional": float(max(0, shares) * price), "stop_distance": stop_distance, "status": "ready"}
