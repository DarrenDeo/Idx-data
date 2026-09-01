from datetime import date

from app.pipeline.incremental import next_start_date


def test_incremental_starts_after_last_date():
    assert next_start_date(date(2026, 8, 27), None, date(2026, 8, 31)) == date(2026, 8, 28)


def test_incremental_uses_listing_date_for_new_symbol():
    assert next_start_date(None, date(2026, 8, 20), date(2026, 8, 31)) == date(2026, 8, 20)


def test_incremental_skips_when_current():
    assert next_start_date(date(2026, 8, 31), None, date(2026, 8, 31)) is None

