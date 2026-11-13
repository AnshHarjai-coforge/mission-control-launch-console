"""Sort, set the deadline, run the three checks, and draft a briefing.

The verdict is an input. This module does not return a new verdict, and it
never sets a report to approved. If the model service cannot be reached, later
model calls are skipped and the status is incomplete.
"""

from dataclasses import dataclass
from datetime import datetime

from app.brief_by import brief_by
from app.briefing import write_briefing
from app.checks import run_checks
from app.classify import classify_report
from app.facts import ReportFacts
from app.model_client import ModelClient


@dataclass(frozen=True)
class PipelineResult:
    vehicle_part: str | None
    vehicle_part_stand_in: bool | None
    model_seriousness: str | None
    deadline_seriousness: str | None
    deadline_minutes: int | None
    due_at: datetime | None
    category: str | None
    hidden_instruction: bool | None
    hidden_instruction_reason: str | None
    missing_information: bool | None
    missing_information_reason: str | None
    panic: bool | None
    panic_reason: str | None
    briefing: str | None
    rounds_run: int | None
    last_review_accepted: bool | None
    last_review_comment: str | None
    status: str


def run_pipeline(client: ModelClient, facts: ReportFacts) -> PipelineResult:
    sort = classify_report(client, facts)
    if (
        sort.unreachable
        or sort.model_seriousness is None
        or sort.vehicle_part is None
        or sort.vehicle_part_stand_in is None
    ):
        return _incomplete_before_checks()

    deadline = brief_by(sort.model_seriousness, facts.broken_limits, facts.filed_at)
    checks = run_checks(client, facts)
    # Spam is only the hidden-instruction flag. It does not change the verdict.
    category = "spam" if checks.hidden_instructions.flagged else "report"
    if checks.any_unreachable:
        return PipelineResult(
            vehicle_part=sort.vehicle_part,
            vehicle_part_stand_in=sort.vehicle_part_stand_in,
            model_seriousness=sort.model_seriousness,
            deadline_seriousness=deadline.seriousness,
            deadline_minutes=deadline.minutes,
            due_at=deadline.due_at,
            category=category,
            hidden_instruction=checks.hidden_instructions.flagged,
            hidden_instruction_reason=checks.hidden_instructions.reason,
            missing_information=checks.missing_information.flagged,
            missing_information_reason=checks.missing_information.reason,
            panic=checks.panic.flagged,
            panic_reason=checks.panic.reason,
            briefing=None,
            rounds_run=0,
            last_review_accepted=None,
            last_review_comment=None,
            status="incomplete",
        )

    outcome = write_briefing(
        client,
        facts,
        deadline_minutes=deadline.minutes,
        checks=checks,
        category=category,
    )
    return PipelineResult(
        vehicle_part=sort.vehicle_part,
        vehicle_part_stand_in=sort.vehicle_part_stand_in,
        model_seriousness=sort.model_seriousness,
        deadline_seriousness=deadline.seriousness,
        deadline_minutes=deadline.minutes,
        due_at=deadline.due_at,
        category=category,
        hidden_instruction=checks.hidden_instructions.flagged,
        hidden_instruction_reason=checks.hidden_instructions.reason,
        missing_information=checks.missing_information.flagged,
        missing_information_reason=checks.missing_information.reason,
        panic=checks.panic.flagged,
        panic_reason=checks.panic.reason,
        briefing=outcome.briefing,
        rounds_run=outcome.rounds_run,
        last_review_accepted=outcome.last_review_accepted,
        last_review_comment=outcome.last_review_comment,
        status=outcome.status,
    )


def _incomplete_before_checks() -> PipelineResult:
    return PipelineResult(
        vehicle_part=None,
        vehicle_part_stand_in=None,
        model_seriousness=None,
        deadline_seriousness=None,
        deadline_minutes=None,
        due_at=None,
        category=None,
        hidden_instruction=None,
        hidden_instruction_reason=None,
        missing_information=None,
        missing_information_reason=None,
        panic=None,
        panic_reason=None,
        briefing=None,
        rounds_run=0,
        last_review_accepted=None,
        last_review_comment=None,
        status="incomplete",
    )
