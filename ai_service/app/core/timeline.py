"""Entries for an application's activity timeline (ApplicationModel.events)."""

from datetime import UTC, datetime
from typing import Any


def timeline_event(step: str, detail: str = "", screenshot: str | None = None) -> dict[str, Any]:
    """`screenshot` is a file name inside the screenshots directory, served per application."""
    return {"at": datetime.now(UTC).isoformat(), "step": step, "detail": detail, "screenshot": screenshot}
