from datetime import datetime

from app.scheduler import JAKARTA, next_scheduled_run


def test_scheduler_uses_same_weekday_when_before_cutoff():
    now = datetime(2026, 8, 31, 17, 0, tzinfo=JAKARTA)
    assert next_scheduled_run(now) == datetime(2026, 8, 31, 18, 0, tzinfo=JAKARTA)


def test_scheduler_skips_weekend():
    friday_evening = datetime(2026, 8, 28, 19, 0, tzinfo=JAKARTA)
    assert next_scheduled_run(friday_evening) == datetime(
        2026, 8, 31, 18, 0, tzinfo=JAKARTA
    )
