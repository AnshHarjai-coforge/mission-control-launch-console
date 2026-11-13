"""The three report checks, started together.

A broken or empty answer stays not flagged, with the reason "check failed".
That failure does not mark the report as spam and does not change the verdict.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace

from app.facts import ReportFacts
from app.model_client import (
    CHECK_TASKS,
    FAILURE_UNREACHABLE,
    TASK_HIDDEN_INSTRUCTIONS,
    TASK_MISSING_INFORMATION,
    TASK_PANIC,
    ModelClient,
    ModelResponse,
    activate_check_barrier,
    restore_check_barrier,
)
from app.prompts import CHECK_SHAPE, check_system, report_lines

CHECK_FAILED = "check failed"


@dataclass(frozen=True)
class CheckResult:
    flagged: bool
    reason: str
    unreachable: bool
    input_tokens: int | None = None
    output_tokens: int | None = None
    call_failure: str | None = None


@dataclass(frozen=True)
class CheckSet:
    hidden_instructions: CheckResult
    missing_information: CheckResult
    panic: CheckResult

    @property
    def any_unreachable(self) -> bool:
        return any(
            item.unreachable
            for item in (
                self.hidden_instructions,
                self.missing_information,
                self.panic,
            )
        )


def run_checks(client: ModelClient, facts: ReportFacts) -> CheckSet:
    """Start hidden instructions, missing information, and panic together.

    The pool has one worker per check so a fake that waits for all three to
    start can see every call. Each call has its own result. One slow check
    does not cancel the others.
    """
    barrier = threading.Barrier(len(CHECK_TASKS))

    def one(task: str) -> CheckResult:
        token = activate_check_barrier(barrier)
        try:
            return _run_one_check(client, task, facts)
        finally:
            restore_check_barrier(token)

    with ThreadPoolExecutor(max_workers=len(CHECK_TASKS)) as executor:
        futures = {task: executor.submit(one, task) for task in CHECK_TASKS}
        results = {task: futures[task].result() for task in CHECK_TASKS}
    return CheckSet(
        hidden_instructions=results[TASK_HIDDEN_INSTRUCTIONS],
        missing_information=results[TASK_MISSING_INFORMATION],
        panic=results[TASK_PANIC],
    )


def _run_one_check(client: ModelClient, task: str, facts: ReportFacts) -> CheckResult:
    response = client.complete(
        task,
        check_system(task),
        report_lines(facts),
        CHECK_SHAPE,
    )
    if response.failure == FAILURE_UNREACHABLE:
        decided = CheckResult(flagged=False, reason=CHECK_FAILED, unreachable=True)
    else:
        decided = interpret_check(response)
    return replace(
        decided,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        call_failure=response.failure,
    )


def interpret_check(response: ModelResponse) -> CheckResult:
    parsed = response.parsed if response.failure is None else None
    if not isinstance(parsed, dict):
        return CheckResult(flagged=False, reason=CHECK_FAILED, unreachable=False)
    flagged = parsed.get("flagged")
    reason = parsed.get("reason")
    if not isinstance(flagged, bool) or not isinstance(reason, str):
        return CheckResult(flagged=False, reason=CHECK_FAILED, unreachable=False)
    return CheckResult(flagged=flagged, reason=reason, unreachable=False)
