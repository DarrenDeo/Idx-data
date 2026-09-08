from datetime import date, timedelta
from decimal import Decimal

from app.analytics import analyze_ohlcv
from app.database.models import OHLCVDaily


def _rows(count: int = 60):
    start = date(2026, 1, 2)
    return [
        OHLCVDaily(
            symbol="BBCA",
            trade_date=start + timedelta(days=index),
            open=Decimal(str(100 + index)),
            high=Decimal(str(102 + index)),
            low=Decimal(str(99 + index)),
            close=Decimal(str(101 + index)),
            volume=1_000 + index,
            source="test",
        )
        for index in range(count)
    ]


def test_analysis_calculates_ma50_and_research_fields():
    result = analyze_ohlcv(_rows(), from_date=date(2026, 2, 20))

    assert result
    latest = result[-1]
    assert latest["ma5"] is not None
    assert latest["ma10"] is not None
    assert latest["ma20"] is not None
    assert latest["ma50"] is not None
    assert latest["simons_score"] is not None
    assert latest["p_model"] is not None
    assert latest["p_final"] is None
    assert latest["probability_status"] == "Benchmark diperlukan untuk model gabungan"
    assert latest["benchmark_observation_count"] == 0
    assert latest["benchmark_required_observations"] == 21
    assert latest["benchmark_status"] == "Benchmark IHSG belum cukup (0/21 hari bursa)"


def test_analysis_uses_benchmark_for_combined_probability():
    prices = _rows()
    benchmarks = [
        OHLCVDaily(
            symbol="IHSG",
            trade_date=row.trade_date,
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            volume=row.volume,
            source="test",
        )
        for row in prices
    ]
    result = analyze_ohlcv(prices, benchmark_rows=benchmarks, from_date=date(2026, 2, 20))

    assert result[-1]["p_final"] is not None
    assert result[-1]["edge"] is not None
    assert result[-1]["probability_status"] == "Baseline terkalibrasi dengan benchmark"
    assert result[-1]["benchmark_observation_count"] == 60
    assert result[-1]["benchmark_status"] == "Benchmark IHSG siap untuk model gabungan"
