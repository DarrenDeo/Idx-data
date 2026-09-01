from datetime import date

from app.pipeline.daily import next_market_start


def test_daily_market_update_starts_after_latest_global_date():
    assert next_market_start(date(2026, 8, 28), date(2026, 8, 31)) == date(2026, 8, 29)


def test_daily_market_update_uses_end_date_for_empty_database():
    assert next_market_start(None, date(2026, 8, 31)) == date(2026, 8, 31)


def test_daily_market_update_skips_when_current():
    assert next_market_start(date(2026, 8, 31), date(2026, 8, 31)) is None
