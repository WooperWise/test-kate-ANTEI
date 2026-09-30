"""Structured event logging: JSONL trail + human-readable console rendering.

Event schema (English, per PLAN.md):
  ts, event, run_id, step_id, agent, tool, correlation_id, duration_ms, payload

Events: run_started/run_finished, plan_created, task_delegated/task_completed/
task_failed, tool_called/tool_result, skill_loaded, review_feedback,
iteration_exhausted, budget_degraded.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def new_run_id() -> str:
    return uuid.uuid4().hex[:10]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class EventBus:
    """Emits harness events to a JSONL file and the console."""

    def __init__(self, run_id: str, outputs_dir: Path, console_format: str, console_enabled: bool = True) -> None:
        self.run_id = run_id
        self.outputs_dir = Path(outputs_dir)
        self.console_format = console_format
        self.console_enabled = console_enabled
        self._file: Path | None = None

    @property
    def log_file(self) -> Path:
        if self._file is None:
            self.outputs_dir.mkdir(parents=True, exist_ok=True)
            self._file = self.outputs_dir / f"run_{self.run_id}.jsonl"
        return self._file

    def emit(
        self,
        event: str,
        *,
        step_id: str | None = None,
        agent: str | None = None,
        tool: str | None = None,
        correlation_id: str | None = None,
        duration_ms: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        record: dict[str, Any] = {
            "ts": _now_iso(),
            "event": event,
            "run_id": self.run_id,
        }
        if step_id is not None:
            record["step_id"] = step_id
        if agent is not None:
            record["agent"] = agent
        if tool is not None:
            record["tool"] = tool
        if correlation_id is not None:
            record["correlation_id"] = correlation_id
        if duration_ms is not None:
            record["duration_ms"] = duration_ms
        if payload is not None:
            record["payload"] = payload

        with self.log_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

        if self.console_enabled:
            detail = " ".join(f"{k}={v}" for k, v in (payload or {}).items() if v is not None)
            line = self.console_format.format(
                ts=record["ts"][11:19],
                event=event,
                agent=agent or "-",
                tool=tool or "-",
                detail=detail,
            )
            print(line, flush=True)
        logger.debug("event %s", event)

    @contextmanager
    def span(
        self,
        event: str,
        **fields: Any,
    ) -> Iterator[None]:
        """Context manager emitting ``<event>`` and ``<event>_finished`` with duration."""
        self.emit(event, **fields)
        start = time.monotonic()
        try:
            yield
        finally:
            self.emit(f"{event}_finished", duration_ms=int((time.monotonic() - start) * 1000), **fields)
