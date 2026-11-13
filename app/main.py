"""FastAPI entrypoint. `uvicorn app.main:app --reload` loads the `app` object."""

from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import Settings, load_settings
from app.db import (
    ConsoleReport,
    approve_report,
    insert_report,
    list_console_reports,
    open_database,
    read_console_report,
    read_created_at,
    save_model_pipeline,
    update_verdict,
)
from app.facts import ReportFacts
from app.limits import check_limits
from app.model_client import ModelClient, build_model_client
from app.pipeline import run_pipeline

_TEMPLATES = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")

_FIELDS = ("name", "station", "wind", "temperature", "fuel", "note")
_READING_FIELDS = ("wind", "temperature", "fuel")
_TEXT_LIMITS = {
    "name": 80,
    "station": 80,
    "note": 4000,
}

HEALTH_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Mission Control</title>
</head>
<body>
  <h1>Mission Control</h1>
  <p>ok</p>
</body>
</html>
"""


@dataclass(frozen=True)
class _ParsedFiling:
    name: str
    station: str
    wind: Decimal
    temperature: Decimal
    fuel: Decimal
    note: str


def create_app() -> FastAPI:
    app = FastAPI(title="Mission Control")
    app.state.settings = load_settings()
    app.state.model_client = build_model_client(app.state.settings)

    @app.get("/health", response_class=HTMLResponse)
    def health() -> HTMLResponse:
        return HTMLResponse(HEALTH_PAGE)

    @app.get("/")
    def filing_form(request: Request) -> HTMLResponse:
        return _render(request, values=_empty_form(), errors={}, filed=False)

    @app.post("/")
    def file_report(
        request: Request,
        name: str = Form(""),
        station: str = Form(""),
        wind: str = Form(""),
        temperature: str = Form(""),
        fuel: str = Form(""),
        note: str = Form(""),
    ) -> HTMLResponse:
        values = {
            "name": name,
            "station": station,
            "wind": wind,
            "temperature": temperature,
            "fuel": fuel,
            "note": note,
        }
        filing, errors = _parse_filing(values)
        if filing is None:
            return _render(request, values=values, errors=errors, filed=False, status_code=400)
        report_id = _save_filing(
            request.app.state.settings,
            filing,
            request.app.state.model_client,
        )
        return _render(request, values=values, errors={}, filed=True, report_id=report_id)

    @app.get("/console")
    def console(request: Request) -> HTMLResponse:
        rows = _load_console_reports(request.app.state.settings)
        reports = [row for row in rows if row.category != "spam"]
        spam = [row for row in rows if row.category == "spam"]
        return _TEMPLATES.TemplateResponse(
            request,
            "console.html",
            {"reports": reports, "spam": spam},
        )

    @app.get("/console/{report_id}")
    def console_report(request: Request, report_id: int) -> HTMLResponse:
        try:
            report = _load_console_report(request.app.state.settings, report_id)
        except LookupError:
            return _TEMPLATES.TemplateResponse(
                request,
                "console_missing.html",
                {},
                status_code=404,
            )
        return _report_page(request, report)

    @app.post("/console/{report_id}/approve")
    def approve(
        request: Request,
        report_id: int,
        approver_name: str = Form(""),
    ) -> HTMLResponse:
        try:
            report = _load_console_report(request.app.state.settings, report_id)
        except LookupError:
            return _TEMPLATES.TemplateResponse(
                request,
                "console_missing.html",
                {},
                status_code=404,
            )
        if report.status == "approved":
            return _report_page(request, report)
        if report.status != "pending_approval" or not report.briefing:
            return _report_page(
                request,
                report,
                approve_error="This report cannot be approved.",
                approver_name=approver_name,
                status_code=400,
            )
        if approver_name.strip() == "":
            return _report_page(
                request,
                report,
                approve_error="Name is blank.",
                approver_name=approver_name,
                status_code=400,
            )
        _store_approval(
            request.app.state.settings,
            report_id,
            approver_name.strip(),
        )
        report = _load_console_report(request.app.state.settings, report_id)
        return _report_page(request, report)

    return app


def _report_page(
    request: Request,
    report: ConsoleReport,
    *,
    approve_error: str = "",
    approver_name: str = "",
    status_code: int = 200,
) -> HTMLResponse:
    return _TEMPLATES.TemplateResponse(
        request,
        "console_report.html",
        {
            "report": report,
            "approve_error": approve_error,
            "approver_name": approver_name,
        },
        status_code=status_code,
    )


def _render(
    request: Request,
    *,
    values: dict[str, str],
    errors: dict[str, str],
    filed: bool,
    status_code: int = 200,
    report_id: int | None = None,
) -> HTMLResponse:
    return _TEMPLATES.TemplateResponse(
        request,
        "file_report.html",
        {
            "values": values,
            "errors": errors,
            "filed": filed,
            "report_id": report_id,
        },
        status_code=status_code,
    )


def _empty_form() -> dict[str, str]:
    return {field: "" for field in _FIELDS}


def _parse_filing(values: dict[str, str]) -> tuple[_ParsedFiling | None, dict[str, str]]:
    errors: dict[str, str] = {}
    for field in _FIELDS:
        if values[field].strip() == "":
            errors[field] = f"{field} is blank."

    readings: dict[str, Decimal] = {}
    for field in _READING_FIELDS:
        if field in errors:
            continue
        number = _reading(values[field])
        if number is None:
            errors[field] = f"{field} must be a number."
        else:
            readings[field] = number

    for field, limit in _TEXT_LIMITS.items():
        if field in errors:
            continue
        if len(values[field]) > limit:
            errors[field] = f"{field} is too long."

    if errors:
        return None, errors

    filing = _ParsedFiling(
        name=values["name"],
        station=values["station"],
        wind=readings["wind"],
        temperature=readings["temperature"],
        fuel=readings["fuel"],
        note=values["note"],
    )
    return filing, {}


def _reading(value: str) -> Decimal | None:
    """Parse a finite decimal. Anything else, including NaN, is not a number."""
    try:
        number = Decimal(value.strip())
    except InvalidOperation:
        return None
    if not number.is_finite():
        return None
    return number


def _database_path(settings: Settings) -> str | None:
    """Use the configured file. A blank path means the default SQLite file."""
    path = settings.database_path.strip()
    return path or None


def _save_filing(
    settings: Settings,
    filing: _ParsedFiling,
    model_client: ModelClient,
) -> int:
    with closing(open_database(_database_path(settings))) as connection:
        report_id = insert_report(
            connection,
            name=filing.name,
            station=filing.station,
            wind=filing.wind,
            temperature=filing.temperature,
            fuel=filing.fuel,
            note=filing.note,
            commit=False,
        )
        filed_at = read_created_at(connection, report_id)
        checked = check_limits(filing.wind, filing.temperature, filing.fuel)
        update_verdict(
            connection,
            report_id,
            verdict=checked.verdict,
            broken_limits=checked.broken_limits,
        )
        connection.commit()
        result = run_pipeline(
            model_client,
            ReportFacts(
                name=filing.name,
                station=filing.station,
                wind=filing.wind,
                temperature=filing.temperature,
                fuel=filing.fuel,
                note=filing.note,
                verdict=checked.verdict,
                broken_limits=checked.broken_limits,
                filed_at=filed_at,
            ),
        )
        save_model_pipeline(
            connection,
            report_id,
            vehicle_part=result.vehicle_part,
            vehicle_part_stand_in=result.vehicle_part_stand_in,
            model_seriousness=result.model_seriousness,
            deadline_seriousness=result.deadline_seriousness,
            deadline_minutes=result.deadline_minutes,
            due_at=result.due_at,
            category=result.category,
            hidden_instruction=result.hidden_instruction,
            hidden_instruction_reason=result.hidden_instruction_reason,
            missing_information=result.missing_information,
            missing_information_reason=result.missing_information_reason,
            panic=result.panic,
            panic_reason=result.panic_reason,
            briefing=result.briefing,
            rounds_run=result.rounds_run,
            last_review_accepted=result.last_review_accepted,
            last_review_comment=result.last_review_comment,
            status=result.status,
        )
        connection.commit()
        return report_id


def _store_approval(settings: Settings, report_id: int, approver_name: str) -> None:
    with closing(open_database(_database_path(settings))) as connection:
        approve_report(
            connection,
            report_id,
            approver_name=approver_name,
            approved_at=datetime.now(UTC),
        )
        connection.commit()


def _load_console_reports(settings: Settings) -> list[ConsoleReport]:
    with closing(open_database(_database_path(settings))) as connection:
        return list_console_reports(connection)


def _load_console_report(settings: Settings, report_id: int) -> ConsoleReport:
    with closing(open_database(_database_path(settings))) as connection:
        return read_console_report(connection, report_id)


app = create_app()
