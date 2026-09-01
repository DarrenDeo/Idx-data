from __future__ import annotations

import logging
import os
import subprocess
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)
JAKARTA = ZoneInfo("Asia/Jakarta")


def next_scheduled_run(now: datetime, hour: int = 18, minute: int = 0) -> datetime:
    local_now = now.astimezone(JAKARTA)
    candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= local_now:
        candidate += timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def main() -> None:
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    hour = int(os.getenv("SCHEDULER_HOUR", "18"))
    minute = int(os.getenv("SCHEDULER_MINUTE", "0"))
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("SCHEDULER_HOUR and SCHEDULER_MINUTE must be valid clock values")

    while True:
        now = datetime.now(JAKARTA)
        scheduled = next_scheduled_run(now, hour, minute)
        delay = max(0.0, (scheduled - now).total_seconds())
        log.info("Next daily market update scheduled=%s", scheduled.isoformat())
        time.sleep(delay)
        end_date = datetime.now(JAKARTA).date().isoformat()
        result = subprocess.run(
            ["idx-platform", "daily", "--end", end_date],
            check=False,
        )
        if result.returncode:
            log.error("Daily market update failed exit_code=%d", result.returncode)
        else:
            log.info("Daily market update completed end=%s", end_date)


if __name__ == "__main__":
    main()
