"""One model interface, the fake used by tests, and the Azure client.

AzureFoundryClient is the only code that reads the API key or opens a network
connection. Tests pass FakeModelClient into the pipeline and never build the
Azure client.
"""

import json
import os
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from contextvars import ContextVar, Token
from dataclasses import dataclass

from app.config import Settings
from app.prompts import parse_code_facts

TASK_SORT = "sort"
TASK_HIDDEN_INSTRUCTIONS = "hidden_instructions"
TASK_MISSING_INFORMATION = "missing_information"
TASK_PANIC = "panic"
TASK_DRAFT = "draft"
TASK_REVIEW = "review"

CHECK_TASKS = (
    TASK_HIDDEN_INSTRUCTIONS,
    TASK_MISSING_INFORMATION,
    TASK_PANIC,
)

FAILURE_UNREACHABLE = "unreachable"
FAILURE_INVALID = "invalid"

DEFAULT_VEHICLE_PART = "weather"
DEFAULT_SERIOUSNESS = "low"
DEFAULT_CHECK_REASON = "none"
DEFAULT_BRIEFING_SUMMARY = "The station filed this report and the note was reviewed."

_CHECK_START_TIMEOUT_SECONDS = 5
_ANTHROPIC_VERSION = "2023-06-01"
_MAX_RESPONSE_BYTES = 1_000_000

_check_barrier: ContextVar[threading.Barrier | None] = ContextVar(
    "mission_control_check_barrier",
    default=None,
)


class Unreachable:
    """Script marker: this model call cannot reach the service."""


class ModelClient:
    """The call every model step uses."""

    def complete(
        self,
        task: str,
        system: str,
        user: str,
        response_shape: Mapping[str, object],
    ) -> "ModelResponse":
        raise NotImplementedError


@dataclass(frozen=True)
class ModelResponse:
    parsed: dict | None
    raw_text: str
    input_tokens: int | None
    output_tokens: int | None
    failure: str | None


@dataclass(frozen=True)
class RecordedCall:
    task: str
    system: str
    user: str
    response_shape: dict[str, object]
    started_at: float
    finished_at: float


class _Default:
    pass


class _Exhausted:
    pass


_DEFAULT = _Default()
_EXHAUSTED = _Exhausted()


def activate_check_barrier(barrier: threading.Barrier) -> Token:
    """Bind the three check calls in this thread to one barrier."""
    return _check_barrier.set(barrier)


def restore_check_barrier(token: Token) -> None:
    _check_barrier.reset(token)


def build_model_client(settings: Settings) -> ModelClient:
    """Return the Azure client only when MODEL_BACKEND is azure.

    A blank backend and the fake backend both use FakeModelClient. Tests pass
    their own fake into the pipeline and do not use this switch.
    """
    if settings.model_backend.strip().lower() == "azure":
        return AzureFoundryClient(
            base_url=settings.azure_foundry_base_url,
            model=settings.azure_foundry_model,
            timeout_seconds=_timeout_seconds(settings.model_timeout_seconds),
        )
    return FakeModelClient()


class FakeModelClient(ModelClient):
    """Scripted answers for tests and for clicking through without Azure.

    A dict is a parsed answer. A string is raw model text. A list is a queue
    of those answers, consumed in order. Unreachable means the service cannot
    be reached. When a task has no script, the fake returns a stable default.

    A check call does not return until the other check calls in that run have
    started.
    """

    def __init__(self, scripts: dict[str, object] | None = None) -> None:
        self.calls: list[RecordedCall] = []
        self._lock = threading.Lock()
        self._queues: dict[str, list[object]] = {}
        self._positions: dict[str, int] = {}
        for task, script in (scripts or {}).items():
            if isinstance(script, list):
                self._queues[task] = list(script)
            else:
                self._queues[task] = [script]
            self._positions[task] = 0

    def complete(
        self,
        task: str,
        system: str,
        user: str,
        response_shape: Mapping[str, object],
    ) -> ModelResponse:
        started_at = time.monotonic()
        self._wait_for_other_checks(task)
        with self._lock:
            scripted = self._next_script(task)
        response = _materialize(scripted, task=task, system=system, user=user)
        finished_at = time.monotonic()
        with self._lock:
            self.calls.append(
                RecordedCall(
                    task=task,
                    system=system,
                    user=user,
                    response_shape=dict(response_shape),
                    started_at=started_at,
                    finished_at=finished_at,
                )
            )
        return response

    def _wait_for_other_checks(self, task: str) -> None:
        if task not in CHECK_TASKS:
            return
        barrier = _check_barrier.get()
        if barrier is None:
            raise TimeoutError("The three checks did not all start")
        try:
            barrier.wait(timeout=_CHECK_START_TIMEOUT_SECONDS)
        except threading.BrokenBarrierError as exc:
            raise TimeoutError("The three checks did not all start") from exc

    def _next_script(self, task: str) -> object:
        if task not in self._queues:
            return _DEFAULT
        position = self._positions[task]
        queue = self._queues[task]
        if position >= len(queue):
            return _EXHAUSTED
        self._positions[task] = position + 1
        return queue[position]


class AzureFoundryClient(ModelClient):
    """Claude on Azure AI Foundry, through the Anthropic Messages API.

    Constructing this client reads AZURE_FOUNDRY_API_KEY. complete is the only
    method that opens a network connection. Tests must not construct this class.
    """

    def __init__(self, *, base_url: str, model: str, timeout_seconds: float) -> None:
        self._api_key = os.environ.get("AZURE_FOUNDRY_API_KEY", "")
        self._base_url = base_url.strip()
        self._model = model.strip()
        self._timeout = timeout_seconds

    def complete(
        self,
        task: str,
        system: str,
        user: str,
        response_shape: Mapping[str, object],
    ) -> ModelResponse:
        if self._api_key == "" or self._base_url == "" or self._model == "":
            return _unreachable_response()
        system_text = (
            f"Task: {task}\n{system}\n\nJSON shape:\n"
            f"{json.dumps(dict(response_shape), sort_keys=True)}"
        )
        payload = {
            "model": self._model,
            "max_tokens": 1024,
            "system": system_text,
            "messages": [{"role": "user", "content": user}],
        }
        request = urllib.request.Request(
            _messages_url(self._base_url),
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "x-api-key": self._api_key,
                "anthropic-version": _ANTHROPIC_VERSION,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body = response.read(_MAX_RESPONSE_BYTES + 1)
        except (urllib.error.URLError, TimeoutError, OSError):
            return _unreachable_response()
        if len(body) > _MAX_RESPONSE_BYTES:
            return _unreachable_response()
        try:
            decoded = body.decode("utf-8")
            envelope = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _unreachable_response()
        raw = _message_text(envelope)
        usage = envelope.get("usage") if isinstance(envelope, dict) else None
        parsed = parse_json_object(raw)
        if parsed is None:
            return ModelResponse(
                parsed=None,
                raw_text=raw,
                input_tokens=_usage_tokens(usage, "input_tokens"),
                output_tokens=_usage_tokens(usage, "output_tokens"),
                failure=FAILURE_INVALID,
            )
        return ModelResponse(
            parsed=parsed,
            raw_text=raw,
            input_tokens=_usage_tokens(usage, "input_tokens"),
            output_tokens=_usage_tokens(usage, "output_tokens"),
            failure=None,
        )


def parse_json_object(raw: str) -> dict | None:
    """Parse one JSON object, including a fenced block. Anything else is None."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(value, dict):
        return value
    return None


def _materialize(scripted: object, *, task: str, system: str, user: str) -> ModelResponse:
    if isinstance(scripted, _Default):
        return _default_response(task, system=system, user=user)
    if isinstance(scripted, Unreachable):
        return _unreachable_response()
    if isinstance(scripted, _Exhausted):
        return _invalid_response("script exhausted", system=system, user=user)
    if isinstance(scripted, str):
        return _response_from_text(scripted, system=system, user=user)
    if isinstance(scripted, dict):
        return _ok_response(scripted, system=system, user=user)
    raise TypeError(f"Unsupported script for {task}")


def _default_response(task: str, *, system: str, user: str) -> ModelResponse:
    if task == TASK_SORT:
        return _ok_response(
            {
                "vehicle_part": DEFAULT_VEHICLE_PART,
                "seriousness": DEFAULT_SERIOUSNESS,
            },
            system=system,
            user=user,
        )
    if task in CHECK_TASKS:
        return _ok_response(
            {"flagged": False, "reason": DEFAULT_CHECK_REASON},
            system=system,
            user=user,
        )
    if task == TASK_DRAFT:
        parsed = parse_code_facts(user)
        if parsed is None:
            return _invalid_response("missing code facts", system=system, user=user)
        verdict, broken_limits, minutes = parsed
        return _ok_response(
            {
                "summary": DEFAULT_BRIEFING_SUMMARY,
                "verdict": verdict,
                "violations": list(broken_limits),
                "brief_by_minutes": minutes,
            },
            system=system,
            user=user,
        )
    if task == TASK_REVIEW:
        return _ok_response(
            {"accepted": True, "feedback": ""},
            system=system,
            user=user,
        )
    return _invalid_response("unknown task", system=system, user=user)


def _ok_response(parsed: dict, *, system: str, user: str) -> ModelResponse:
    raw = json.dumps(parsed)
    return ModelResponse(
        parsed=parsed,
        raw_text=raw,
        input_tokens=_word_count(system) + _word_count(user),
        output_tokens=_word_count(raw),
        failure=None,
    )


def _response_from_text(raw: str, *, system: str, user: str) -> ModelResponse:
    parsed = parse_json_object(raw)
    if parsed is None:
        return ModelResponse(
            parsed=None,
            raw_text=raw,
            input_tokens=_word_count(system) + _word_count(user),
            output_tokens=_word_count(raw),
            failure=FAILURE_INVALID,
        )
    return ModelResponse(
        parsed=parsed,
        raw_text=raw,
        input_tokens=_word_count(system) + _word_count(user),
        output_tokens=_word_count(raw),
        failure=None,
    )


def _invalid_response(raw: str, *, system: str, user: str) -> ModelResponse:
    return ModelResponse(
        parsed=None,
        raw_text=raw,
        input_tokens=_word_count(system) + _word_count(user),
        output_tokens=_word_count(raw),
        failure=FAILURE_INVALID,
    )


def _unreachable_response() -> ModelResponse:
    return ModelResponse(
        parsed=None,
        raw_text="",
        input_tokens=None,
        output_tokens=None,
        failure=FAILURE_UNREACHABLE,
    )


def _word_count(text: str) -> int:
    return len(text.split())


def _timeout_seconds(raw: str) -> float:
    text = raw.strip()
    if text == "":
        return 60
    try:
        value = float(text)
    except ValueError:
        return 60
    if value <= 0:
        return 60
    return value


def _messages_url(base_url: str) -> str:
    url = base_url.rstrip("/")
    if url.endswith("/v1/messages"):
        return url
    if url.endswith("/v1"):
        return url + "/messages"
    return url + "/v1/messages"


def _message_text(envelope: object) -> str:
    if not isinstance(envelope, dict):
        return ""
    content = envelope.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


def _usage_tokens(usage: object, name: str) -> int | None:
    if not isinstance(usage, dict):
        return None
    value = usage.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0:
        return None
    return value
