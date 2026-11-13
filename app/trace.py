"""One recorded row for each pipeline step that actually ran.

Rounds that did not run are not recorded. Code steps store 0 tokens. Model
steps store the token counts from the call. Pricing uses the cost function
and does not change what a step decided.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.cost import report_cost, step_cost
from app.model_client import ModelResponse

REPORT_SAVED = "Report saved"
LIMITS_AND_VERDICT = "Launch limits and verdict"
VEHICLE_AND_SERIOUSNESS = "Vehicle part and seriousness"
DEADLINE = "Deadline"
HIDDEN_CHECK = "Hidden-instruction check"
MISSING_CHECK = "Missing-information check"
PANIC_CHECK = "Panic check"
SPAM_LABEL = "Spam label"
WAITING = "Waiting for the Flight Director"


def draft_name(round_number: int) -> str:
    return f"Draft round {round_number}"


def review_name(round_number: int) -> str:
    return f"Review round {round_number}"


@dataclass(frozen=True)
class RecordedStep:
    name: str
    kind: str
    round_number: int | None
    input_tokens: int | None
    output_tokens: int | None
    outcome: str
    detail: str


@dataclass(frozen=True)
class PricedStep:
    order: int
    name: str
    kind: str
    round_number: int | None
    input_tokens: int | None
    output_tokens: int | None
    cost: Decimal
    outcome: str
    detail: str


def code_step(name: str, *, detail: str) -> RecordedStep:
    return RecordedStep(
        name=name,
        kind="code",
        round_number=None,
        input_tokens=0,
        output_tokens=0,
        outcome="ok",
        detail=detail,
    )


def model_step(
    name: str,
    response: ModelResponse,
    *,
    outcome: str,
    detail: str,
    round_number: int | None = None,
) -> RecordedStep:
    return RecordedStep(
        name=name,
        kind="model",
        round_number=round_number,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        outcome=outcome,
        detail=detail,
    )


def price_steps(
    steps: Sequence[RecordedStep],
    *,
    input_usd_per_million: Decimal,
    output_usd_per_million: Decimal,
) -> tuple[tuple[PricedStep, ...], Decimal]:
    """Price each step in order and return the steps plus the report total."""
    priced: list[PricedStep] = []
    costs: list[Decimal] = []
    for order, step in enumerate(steps, start=1):
        cost = step_cost(
            step.input_tokens,
            step.output_tokens,
            input_usd_per_million=input_usd_per_million,
            output_usd_per_million=output_usd_per_million,
        )
        costs.append(cost)
        priced.append(
            PricedStep(
                order=order,
                name=step.name,
                kind=step.kind,
                round_number=step.round_number,
                input_tokens=step.input_tokens,
                output_tokens=step.output_tokens,
                cost=cost,
                outcome=step.outcome,
                detail=step.detail,
            )
        )
    return tuple(priced), report_cost(costs)
