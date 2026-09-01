from __future__ import annotations

import subprocess
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


class JobManager:
    """Run one allow-listed CLI job at a time without blocking HTTP requests."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._current: JobState | None = None

    def start(self, name: str, command: list[str]) -> dict[str, object]:
        with self._lock:
            if self._current and self._current.status == "RUNNING":
                raise JobAlreadyRunningError(self._current.name)
            state = JobState(
                id=uuid4().hex,
                name=name,
                command=command,
                status="RUNNING",
                started_at=datetime.now(timezone.utc).isoformat(),
            )
            self._current = state
        Thread(target=self._execute, args=(state,), daemon=True).start()
        return state.public()

    def current(self) -> dict[str, object] | None:
        with self._lock:
            return self._current.public() if self._current else None

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
