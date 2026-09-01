from __future__ import annotations

import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from threading import Lock, Thread
from uuid import uuid4


@dataclass
class JobState:
    id: str
    name: str
    command: list[str]
    status: str
    started_at: str
    finished_at: str | None = None
    exit_code: int | None = None
    output: str = ""

    def public(self) -> dict[str, object]:
        value = asdict(self)
        value["command"] = " ".join(self.command)
        return value


class JobAlreadyRunningError(RuntimeError):
    pass


class JobCooldownError(RuntimeError):
    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after
        super().__init__(str(retry_after))


class JobManager:
    """Run one allow-listed CLI job at a time without blocking HTTP requests."""

    def __init__(self, cooldown_seconds: int = 30) -> None:
        self._lock = Lock()
        self._current: JobState | None = None
        self._cooldown_seconds = cooldown_seconds
        self._last_started = 0.0

    def start(self, name: str, command: list[str]) -> dict[str, object]:
        with self._lock:
            if self._current and self._current.status == "RUNNING":
                raise JobAlreadyRunningError(self._current.name)
            elapsed = time.monotonic() - self._last_started
            if elapsed < self._cooldown_seconds:
                raise JobCooldownError(max(1, round(self._cooldown_seconds - elapsed)))
            state = JobState(
                id=uuid4().hex,
                name=name,
                command=command,
                status="RUNNING",
                started_at=datetime.now(timezone.utc).isoformat(),
            )
            self._current = state
            self._last_started = time.monotonic()
        Thread(target=self._execute, args=(state,), daemon=True).start()
        return state.public()

    def current(self) -> dict[str, object] | None:
        with self._lock:
            return self._current.public() if self._current else None

    def reset(self) -> None:
        """Clear a finished UI job without deleting any downloaded data."""
        with self._lock:
            if self._current and self._current.status == "RUNNING":
                raise JobAlreadyRunningError(self._current.name)
            self._current = None

    def _execute(self, state: JobState) -> None:
        try:
            result = subprocess.run(
                state.command,
                check=False,
                capture_output=True,
                text=True,
            )
            output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part)
            with self._lock:
                state.exit_code = result.returncode
                state.status = "SUCCESS" if result.returncode == 0 else "FAILED"
                state.output = output[-20_000:]
                state.finished_at = datetime.now(timezone.utc).isoformat()
        except Exception as exc:  # pragma: no cover - defensive process boundary
            with self._lock:
                state.status = "FAILED"
                state.output = f"{type(exc).__name__}: {exc}"
                state.finished_at = datetime.now(timezone.utc).isoformat()


job_manager = JobManager()
