"""Page helpers for the console. They do not change a verdict or a deadline."""

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol


class _BoardRow(Protocol):
    verdict: str | None
    status: str | None


def utc_stamp() -> str:
    """Return the current UTC time for the masthead clock."""
    return datetime.now(UTC).strftime("%Y-%m-%d  %H:%M:%S UTC")


def due_label(raw: object) -> str:
    """Show a deadline as a short UTC time. An unreadable value is left as stored."""
    if raw is None:
        return ""
    text = str(raw).strip()
    if text == "":
        return ""
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return text
    if parsed.tzinfo is None:
        return parsed.strftime("%Y-%m-%d %H:%M")
    return parsed.strftime("%Y-%m-%d %H:%M UTC")


def meter_width(raw: object, kind: str) -> str:
    """Map one reading onto a 0–100% bar. Values outside the scale clamp.

    Wind uses 0–25 kt. Temperature uses 0–40 °C. Fuel uses 90–100%.
    """
    try:
        value = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError):
        return "0%"
    if not value.is_finite():
        return "0%"
    if kind == "wind":
        span = value / Decimal(25) * 100
    elif kind == "temperature":
        span = value / Decimal(40) * 100
    elif kind == "fuel":
        span = (value - Decimal(90)) / Decimal(10) * 100
    else:
        return "0%"
    if span < 0:
        span = Decimal(0)
    elif span > 100:
        span = Decimal(100)
    return f"{int(span)}%"


def board_tally(reports: Sequence[_BoardRow], spam: Sequence[_BoardRow]) -> dict[str, int]:
    """Count the boards. A spam go stays in the spam count, not the go count."""
    waiting = (*reports, *spam)
    return {
        "go": sum(item.verdict == "go" for item in reports),
        "nogo": sum(item.verdict == "no_go" for item in reports),
        "awaiting": sum(item.status == "pending_approval" for item in waiting),
        "spam": len(spam),
    }
