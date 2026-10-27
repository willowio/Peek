"""Small shared model for collector results and evidence-based states."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

Status = Literal["ok", "partial", "unavailable", "error"]
CheckState = Literal["Enabled", "Disabled", "Unknown", "Unavailable", "Unsupported", "Error", "Partial"]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass
class Result:
    collector: str
    status: Status
    data: Any = field(default_factory=list)
    collected_at: str = field(default_factory=now)
    source: str = ""
    limitations: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    duration_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def status_from(errors: list[str], data: Any, *, available: bool = True) -> Status:
    if not available:
        return "unavailable"
    if errors:
        return "partial" if data else "error"
    return "ok"
