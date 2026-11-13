"""Briefing deadline from seriousness and the limit check.

This does not read the database and does not call a model. High, medium, and
low are 5, 15, and 30 minutes. Any broken limit counts as high.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

_MINUTES_BY_SERIOUSNESS = {
    "high": 5,
    "medium": 15,
    "low": 30,
}


@dataclass(frozen=True)
class Deadline:
    """The seriousness the deadline uses, how many minutes, and the due time."""

    seriousness: str
    minutes: int
    due_at: datetime


def brief_by(
    model_seriousness: str,
    broken_limits: Sequence[str],
    filed_at: datetime,
) -> Deadline:
    """Return the deadline for one filing.

    The due time is the filing time plus the minutes. Any broken limit counts
    as high, including when the model seriousness is low.
    """
    if isinstance(broken_limits, (str, bytes)) or not isinstance(broken_limits, Sequence):
        raise TypeError("broken limits must be a sequence of names")
    if len(broken_limits) > 0:
        seriousness = "high"
    elif model_seriousness not in _MINUTES_BY_SERIOUSNESS:
        raise ValueError("seriousness must be high, medium, or low")
    else:
        seriousness = model_seriousness
    minutes = _MINUTES_BY_SERIOUSNESS[seriousness]
    return Deadline(
        seriousness=seriousness,
        minutes=minutes,
        due_at=filed_at + timedelta(minutes=minutes),
    )
