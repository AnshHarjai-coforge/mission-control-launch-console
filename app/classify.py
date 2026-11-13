"""Sort a report into a vehicle part and a seriousness.

A missing or illegal answer becomes vehicle part ``not specified`` and
seriousness medium, unless that part of the answer was on the list. The
replacement does not change the launch verdict.
"""

from dataclasses import dataclass

from app.facts import ReportFacts
from app.model_client import (
    FAILURE_UNREACHABLE,
    TASK_SORT,
    ModelClient,
    ModelResponse,
)
from app.prompts import SORT_SHAPE, report_lines, sort_system

VEHICLE_PARTS = (
    "propulsion",
    "avionics",
    "weather",
    "ground support",
    "communications",
    "propellant",
    "structures",
    "range safety",
    "other",
)
SERIOUSNESS_LEVELS = ("high", "medium", "low")
STAND_IN_PART = "not specified"
STAND_IN_SERIOUSNESS = "medium"

_PARTS = frozenset(VEHICLE_PARTS)
_LEVELS = frozenset(SERIOUSNESS_LEVELS)


@dataclass(frozen=True)
class SortResult:
    vehicle_part: str | None
    vehicle_part_stand_in: bool | None
    model_seriousness: str | None
    unreachable: bool


def classify_report(client: ModelClient, facts: ReportFacts) -> SortResult:
    response = client.complete(
        TASK_SORT,
        sort_system(VEHICLE_PARTS, SERIOUSNESS_LEVELS),
        report_lines(facts),
        SORT_SHAPE,
    )
    if response.failure == FAILURE_UNREACHABLE:
        return SortResult(
            vehicle_part=None,
            vehicle_part_stand_in=None,
            model_seriousness=None,
            unreachable=True,
        )
    return interpret_sort(response)


def interpret_sort(response: ModelResponse) -> SortResult:
    parsed = response.parsed if response.failure is None else None
    part: str | None = None
    seriousness: str | None = None
    if isinstance(parsed, dict):
        raw_part = parsed.get("vehicle_part")
        raw_seriousness = parsed.get("seriousness")
        if isinstance(raw_part, str) and raw_part.strip() in _PARTS:
            part = raw_part.strip()
        if isinstance(raw_seriousness, str) and raw_seriousness.strip() in _LEVELS:
            seriousness = raw_seriousness.strip()
    return SortResult(
        vehicle_part=part if part is not None else STAND_IN_PART,
        vehicle_part_stand_in=part is None,
        model_seriousness=seriousness if seriousness is not None else STAND_IN_SERIOUSNESS,
        unreachable=False,
    )
