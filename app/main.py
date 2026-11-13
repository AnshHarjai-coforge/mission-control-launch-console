"""FastAPI entrypoint. `uvicorn app.main:app --reload` loads the `app` object."""

from contextlib import closing
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.brief_by import brief_by
from app.config import Settings, load_settings
from app.db import (
    ConsoleReport,
    insert_report,
    list_console_reports,
    open_database,
    read_console_report,
    read_created_at,
    update_launch_verdict,
)
from app.limits import check_limits

_TEMPLATES = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")

_FIELDS = ("name", "station", "wind", "temperature", "fuel", "note")
_READING_FIELDS = ("wind", "temperature", "fuel")
_TEXT_LIMITS = {
    "name": 80,
    "station": 80,
    "note": 4000,
}
# Sorting is not part of this branch. Until it exists, the note is treated as low.
_MODEL_SERIOUSNESS_UNTIL_SORTING = "low"

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
        report_id = _save_filing(request.app.state.settings, filing)
        return _render(request, values=values, errors={}, filed=True, report_id=report_id)

    @app.get("/console")
    def console(request: Request) -> HTMLResponse:
        reports = _load_console_reports(request.app.state.settings)
        return _TEMPLATES.TemplateResponse(
            request,
            "console.html",
            {"reports": reports},
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
        return _TEMPLATES.TemplateResponse(
            request,
            "console_report.html",
            {"report": report},
        )

    return app


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


def _save_filing(settings: Settings, filing: _ParsedFiling) -> int:
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
        deadline = brief_by(
            _MODEL_SERIOUSNESS_UNTIL_SORTING,
            checked.broken_limits,
            filed_at,
        )
        update_launch_verdict(
            connection,
            report_id,
            verdict=checked.verdict,
            broken_limits=checked.broken_limits,
            model_seriousness=_MODEL_SERIOUSNESS_UNTIL_SORTING,
            deadline_seriousness=deadline.seriousness,
            deadline_minutes=deadline.minutes,
            due_at=deadline.due_at,
        )
        connection.commit()
        return report_id


def _load_console_reports(settings: Settings) -> list[ConsoleReport]:
    with closing(open_database(_database_path(settings))) as connection:
        return list_console_reports(connection)


def _load_console_report(settings: Settings, report_id: int) -> ConsoleReport:
    with closing(open_database(_database_path(settings))) as connection:
        return read_console_report(connection, report_id)


app = create_app()
