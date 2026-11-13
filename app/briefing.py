"""Up to three draft-and-review rounds.

A round is one draft and, when the draft matches the code, one review. The
loop stops when the review says yes. A review comment is passed unchanged into
the next draft. A draft whose verdict, broken limits, or deadline minutes
disagree with the code is rejected, and that reason is passed into the next
draft. The model is not the source of those three facts.
"""

from dataclasses import dataclass

from app.checks import CheckSet
from app.facts import ReportFacts
from app.model_client import (
    FAILURE_UNREACHABLE,
    TASK_DRAFT,
    TASK_REVIEW,
    ModelClient,
    ModelResponse,
)
from app.prompts import (
    DRAFT_SHAPE,
    REVIEW_SHAPE,
    draft_system,
    draft_user,
    review_system,
    review_user,
)
from app.trace import RecordedStep, draft_name, model_step, review_name

_MAX_ROUNDS = 3


@dataclass(frozen=True)
class Draft:
    summary: str
    verdict: str
    violations: tuple[str, ...]
    brief_by_minutes: int


@dataclass(frozen=True)
class Review:
    accepted: bool
    feedback: str


@dataclass(frozen=True)
class BriefingOutcome:
    briefing: str | None
    rounds_run: int
    last_review_accepted: bool
    last_review_comment: str
    status: str
    unreachable: bool
    steps: tuple[RecordedStep, ...]


def write_briefing(
    client: ModelClient,
    facts: ReportFacts,
    *,
    deadline_minutes: int,
    checks: CheckSet,
    category: str,
) -> BriefingOutcome:
    usable: str | None = None
    comment = ""
    accepted = False
    rounds = 0
    steps: list[RecordedStep] = []
    for _ in range(_MAX_ROUNDS):
        rounds += 1
        draft_response = client.complete(
            TASK_DRAFT,
            draft_system(),
            _draft_user(facts, checks, category, deadline_minutes, comment),
            DRAFT_SHAPE,
        )
        if draft_response.failure == FAILURE_UNREACHABLE:
            steps.append(
                model_step(
                    draft_name(rounds),
                    draft_response,
                    outcome="error",
                    detail="The model could not be reached.",
                    round_number=rounds,
                )
            )
            return _incomplete(usable, rounds, accepted=False, comment=comment, steps=tuple(steps))
        draft = _draft_from(draft_response)
        if draft is None:
            steps.append(
                model_step(
                    draft_name(rounds),
                    draft_response,
                    outcome="error",
                    detail="The draft was the wrong shape.",
                    round_number=rounds,
                )
            )
            comment = "The draft was the wrong shape."
            accepted = False
            continue
        mismatch = _mismatch_reason(
            draft,
            verdict=facts.verdict,
            broken_limits=facts.broken_limits,
            minutes=deadline_minutes,
        )
        if mismatch is not None:
            steps.append(
                model_step(
                    draft_name(rounds),
                    draft_response,
                    outcome="error",
                    detail=mismatch,
                    round_number=rounds,
                )
            )
            comment = mismatch
            accepted = False
            continue
        steps.append(
            model_step(
                draft_name(rounds),
                draft_response,
                outcome="ok",
                detail="Draft matches the code.",
                round_number=rounds,
            )
        )
        usable = draft.summary
        review_response = client.complete(
            TASK_REVIEW,
            review_system(),
            _review_user(facts, checks, category, draft.summary),
            REVIEW_SHAPE,
        )
        if review_response.failure == FAILURE_UNREACHABLE:
            steps.append(
                model_step(
                    review_name(rounds),
                    review_response,
                    outcome="error",
                    detail="The model could not be reached.",
                    round_number=rounds,
                )
            )
            return _incomplete(usable, rounds, accepted=False, comment=comment, steps=tuple(steps))
        review = _review_from(review_response)
        if review is None:
            steps.append(
                model_step(
                    review_name(rounds),
                    review_response,
                    outcome="error",
                    detail="The review was the wrong shape.",
                    round_number=rounds,
                )
            )
            comment = "The review was the wrong shape."
            accepted = False
            continue
        steps.append(
            model_step(
                review_name(rounds),
                review_response,
                outcome="ok",
                detail="Accepted." if review.accepted else "Changes requested.",
                round_number=rounds,
            )
        )
        comment = review.feedback
        if review.accepted:
            accepted = True
            break
        accepted = False
    status = "pending_approval" if usable is not None else "incomplete"
    return BriefingOutcome(
        briefing=usable,
        rounds_run=rounds,
        last_review_accepted=accepted,
        last_review_comment=comment,
        status=status,
        unreachable=False,
        steps=tuple(steps),
    )


def _draft_user(
    facts: ReportFacts,
    checks: CheckSet,
    category: str,
    deadline_minutes: int,
    previous_comment: str,
) -> str:
    return draft_user(
        facts,
        hidden_flagged=checks.hidden_instructions.flagged,
        hidden_reason=checks.hidden_instructions.reason,
        missing_flagged=checks.missing_information.flagged,
        missing_reason=checks.missing_information.reason,
        panic_flagged=checks.panic.flagged,
        panic_reason=checks.panic.reason,
        category=category,
        deadline_minutes=deadline_minutes,
        previous_comment=previous_comment,
    )


def _review_user(
    facts: ReportFacts,
    checks: CheckSet,
    category: str,
    summary: str,
) -> str:
    return review_user(
        facts,
        hidden_flagged=checks.hidden_instructions.flagged,
        hidden_reason=checks.hidden_instructions.reason,
        missing_flagged=checks.missing_information.flagged,
        missing_reason=checks.missing_information.reason,
        panic_flagged=checks.panic.flagged,
        panic_reason=checks.panic.reason,
        category=category,
        summary=summary,
    )


def _draft_from(response: ModelResponse) -> Draft | None:
    parsed = response.parsed if response.failure is None else None
    if not isinstance(parsed, dict):
        return None
    summary = parsed.get("summary")
    verdict = parsed.get("verdict")
    violations = parsed.get("violations")
    minutes = parsed.get("brief_by_minutes")
    if not isinstance(summary, str) or summary.strip() == "":
        return None
    if verdict not in {"go", "no_go"}:
        return None
    if not isinstance(violations, list) or any(not isinstance(item, str) for item in violations):
        return None
    if isinstance(minutes, bool) or not isinstance(minutes, int):
        return None
    return Draft(
        summary=summary,
        verdict=verdict,
        violations=tuple(violations),
        brief_by_minutes=minutes,
    )


def _review_from(response: ModelResponse) -> Review | None:
    parsed = response.parsed if response.failure is None else None
    if not isinstance(parsed, dict):
        return None
    accepted = parsed.get("accepted")
    feedback = parsed.get("feedback")
    if not isinstance(accepted, bool) or not isinstance(feedback, str):
        return None
    return Review(accepted=accepted, feedback=feedback)


def _mismatch_reason(
    draft: Draft,
    *,
    verdict: str,
    broken_limits: tuple[str, ...],
    minutes: int,
) -> str | None:
    reasons: list[str] = []
    if draft.verdict != verdict:
        reasons.append(f"The draft verdict does not match the code verdict {verdict}.")
    if tuple(sorted(draft.violations)) != tuple(sorted(broken_limits)):
        shown = ", ".join(broken_limits) if broken_limits else "none"
        reasons.append(f"The draft broken limits do not match the code: {shown}.")
    if draft.brief_by_minutes != minutes:
        reasons.append(f"The draft deadline minutes do not match the code: {minutes}.")
    if not reasons:
        return None
    return " ".join(reasons)


def _incomplete(
    briefing: str | None,
    rounds: int,
    *,
    accepted: bool,
    comment: str,
    steps: tuple[RecordedStep, ...],
) -> BriefingOutcome:
    return BriefingOutcome(
        briefing=briefing,
        rounds_run=rounds,
        last_review_accepted=accepted,
        last_review_comment=comment,
        status="incomplete",
        unreachable=True,
        steps=steps,
    )
