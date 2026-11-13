"""Sort, set the deadline, run the three checks, and draft a briefing.

The verdict is an input. This module does not return a new verdict, and it
never sets a report to approved. If the model service cannot be reached, later
model calls are skipped and the status is incomplete.
"""

from dataclasses import dataclass
from datetime import datetime

from app.brief_by import brief_by
from app.briefing import write_briefing
from app.checks import CHECK_FAILED, CheckResult, run_checks
from app.classify import SortResult, classify_report
from app.facts import ReportFacts
from app.model_client import FAILURE_INVALID, FAILURE_UNREACHABLE, ModelClient
from app.trace import (
    DEADLINE,
    HIDDEN_CHECK,
    MISSING_CHECK,
    PANIC_CHECK,
    SPAM_LABEL,
    VEHICLE_AND_SERIOUSNESS,
    WAITING,
    RecordedStep,
    code_step,
)


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
    steps: tuple[RecordedStep, ...]


def run_pipeline(client: ModelClient, facts: ReportFacts) -> PipelineResult:
    sort = classify_report(client, facts)
    steps: list[RecordedStep] = [_sort_step(sort)]
    if (
        sort.unreachable
        or sort.model_seriousness is None
        or sort.vehicle_part is None
        or sort.vehicle_part_stand_in is None
    ):
        return _incomplete_before_checks(tuple(steps))

    deadline = brief_by(sort.model_seriousness, facts.broken_limits, facts.filed_at)
    steps.append(code_step(DEADLINE, detail=f"{deadline.minutes} minutes."))
    checks = run_checks(client, facts)
    steps.append(_check_step(HIDDEN_CHECK, checks.hidden_instructions))
    steps.append(_check_step(MISSING_CHECK, checks.missing_information))
    steps.append(_check_step(PANIC_CHECK, checks.panic))
    # Spam is only the hidden-instruction flag. It does not change the verdict.
    category = "spam" if checks.hidden_instructions.flagged else "report"
    if checks.hidden_instructions.flagged:
        steps.append(code_step(SPAM_LABEL, detail="Labeled spam."))
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
            steps=tuple(steps),
        )

    outcome = write_briefing(
        client,
        facts,
        deadline_minutes=deadline.minutes,
        checks=checks,
        category=category,
    )
    steps.extend(outcome.steps)
    if outcome.status == "pending_approval":
        steps.append(code_step(WAITING, detail="Waiting for approval."))
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
        steps=tuple(steps),
    )


def _incomplete_before_checks(steps: tuple[RecordedStep, ...]) -> PipelineResult:
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
        steps=steps,
    )


def _sort_step(sort: SortResult) -> RecordedStep:
    if sort.unreachable or sort.call_failure == FAILURE_UNREACHABLE:
        outcome = "error"
        detail = "The model could not be reached."
    elif sort.call_failure == FAILURE_INVALID:
        outcome = "error"
        detail = "The answer was replaced."
    elif sort.vehicle_part_stand_in:
        outcome = "ok"
        detail = "Vehicle part replaced with not specified."
    else:
        outcome = "ok"
        detail = "Sorted."
    return RecordedStep(
        name=VEHICLE_AND_SERIOUSNESS,
        kind="model",
        round_number=None,
        input_tokens=sort.input_tokens,
        output_tokens=sort.output_tokens,
        outcome=outcome,
        detail=detail,
    )


def _check_step(name: str, check: CheckResult) -> RecordedStep:
    if check.unreachable or check.call_failure == FAILURE_UNREACHABLE:
        outcome = "error"
        detail = "The model could not be reached."
    elif check.call_failure == FAILURE_INVALID or check.reason == CHECK_FAILED:
        outcome = "error"
        detail = "check failed"
    else:
        outcome = "ok"
        detail = check.reason.strip() or "Checked."
    return RecordedStep(
        name=name,
        kind="model",
        round_number=None,
        input_tokens=check.input_tokens,
        output_tokens=check.output_tokens,
        outcome=outcome,
        detail=detail,
    )
