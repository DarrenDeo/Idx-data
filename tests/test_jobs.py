import subprocess
import time
from threading import Event

import pytest

from app.api.jobs import JobAlreadyRunningError, JobManager


def test_job_manager_records_success(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "loaded 12", ""),
    )
    manager = JobManager()
    manager.start("Daily", ["idx-platform", "daily"])

    for _ in range(100):
        current = manager.current()
        if current and current["status"] != "RUNNING":
            break
        time.sleep(0.01)

    assert current["status"] == "SUCCESS"
    assert current["exit_code"] == 0
    assert current["output"] == "loaded 12"


def test_job_manager_allows_only_one_running_job(monkeypatch):
    release = Event()

    def wait_for_release(*args, **kwargs):
        release.wait(timeout=2)
        return subprocess.CompletedProcess(args[0], 0, "done", "")

    monkeypatch.setattr(subprocess, "run", wait_for_release)
    manager = JobManager()
    manager.start("First", ["idx-platform", "daily"])

    with pytest.raises(JobAlreadyRunningError, match="First"):
        manager.start("Second", ["idx-platform", "sync-symbols"])

    release.set()
