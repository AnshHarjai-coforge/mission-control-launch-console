"""SQLite storage for launch reports.

Uses the standard library only. Wind, temperature, fuel, and cost are stored
as text so a decimal such as 25.1 round-trips exactly. Columns that later
branches fill in are created here and left unset.
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

DEFAULT_DATABASE_PATH = Path("data") / "mission-control.sqlite"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    name TEXT NOT NULL,
    station TEXT NOT NULL,
    wind TEXT NOT NULL,
    temperature TEXT NOT NULL,
    fuel TEXT NOT NULL,
    note TEXT NOT NULL,
    verdict TEXT CHECK (verdict IS NULL OR verdict IN ('go', 'no_go')),
    broken_limits TEXT,
    vehicle_part TEXT,
    vehicle_part_stand_in INTEGER CHECK (
        vehicle_part_stand_in IS NULL OR vehicle_part_stand_in IN (0, 1)
    ),
    model_seriousness TEXT CHECK (
        model_seriousness IS NULL OR model_seriousness IN ('high', 'medium', 'low')
    ),
    deadline_seriousness TEXT CHECK (
        deadline_seriousness IS NULL
        OR deadline_seriousness IN ('high', 'medium', 'low')
    ),
    deadline_minutes INTEGER,
    due_at TEXT,
    category TEXT CHECK (category IS NULL OR category IN ('report', 'spam')),
    hidden_instruction INTEGER CHECK (
        hidden_instruction IS NULL OR hidden_instruction IN (0, 1)
    ),
    hidden_instruction_reason TEXT,
    missing_information INTEGER CHECK (
        missing_information IS NULL OR missing_information IN (0, 1)
    ),
    missing_information_reason TEXT,
    panic INTEGER CHECK (panic IS NULL OR panic IN (0, 1)),
    panic_reason TEXT,
    briefing TEXT,
    rounds_run INTEGER,
    last_review_accepted INTEGER CHECK (
        last_review_accepted IS NULL OR last_review_accepted IN (0, 1)
    ),
    last_review_comment TEXT,
    status TEXT CHECK (
        status IS NULL
        OR status IN ('pending_approval', 'approved', 'incomplete')
    ),
    approved_at TEXT,
    approver_name TEXT,
    total_cost TEXT
);

CREATE TABLE IF NOT EXISTS trace_steps (
    id INTEGER PRIMARY KEY,
    report_id INTEGER NOT NULL REFERENCES reports(id),
    step_order INTEGER,
    name TEXT,
    kind TEXT CHECK (kind IS NULL OR kind IN ('code', 'model')),
    round_number INTEGER,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost TEXT,
    outcome TEXT CHECK (outcome IS NULL OR outcome IN ('ok', 'error')),
    detail TEXT
);

CREATE INDEX IF NOT EXISTS idx_trace_steps_report_id ON trace_steps(report_id);
"""


@dataclass(frozen=True)
class FiledReport:
    id: int
    name: str
    station: str
    wind: Decimal
    temperature: Decimal
    fuel: Decimal
    note: str


@dataclass(frozen=True)
class ConsoleReport:
    id: int
    name: str
    station: str
    wind: str
    temperature: str
    fuel: str
    note: str
    verdict: str | None
    broken_limits: tuple[str, ...]
    deadline_minutes: int | None
    due_at: str | None

    @property
    def broken_limits_label(self) -> str:
        if not self.broken_limits:
            return "none"
        return ", ".join(self.broken_limits)

    @property
    def deadline_label(self) -> str:
        if self.deadline_minutes is None:
            return ""
        return f"{self.deadline_minutes} minutes"


def open_database(path: str | Path | None = None) -> sqlite3.Connection:
    """Open the database, creating the parent folder and tables if needed.

    The default file is ``data/mission-control.sqlite``.
    """
    database_path = DEFAULT_DATABASE_PATH if path is None else Path(path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(_SCHEMA)
    return connection


def insert_report(
    connection: sqlite3.Connection,
    *,
    name: str,
    station: str,
    wind: Decimal | str | float,
    temperature: Decimal | str | float,
    fuel: Decimal | str | float,
    note: str,
    commit: bool = True,
) -> int:
    """Insert the six filed fields and leave every other column unset.

    Pass commit=False when the caller still needs to update this row in the
    same transaction.
    """
    cursor = connection.execute(
        """
        INSERT INTO reports (created_at, name, station, wind, temperature, fuel, note)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now(UTC).isoformat(),
            name,
            station,
            _store_decimal(wind),
            _store_decimal(temperature),
            _store_decimal(fuel),
            note,
        ),
    )
    report_id = cursor.lastrowid
    if report_id is None:
        raise RuntimeError("SQLite did not return a report id")
    if commit:
        connection.commit()
    return report_id


def read_report(connection: sqlite3.Connection, report_id: int) -> FiledReport:
    """Read the six filed fields for one saved report."""
    row = connection.execute(
        """
        SELECT id, name, station, wind, temperature, fuel, note
        FROM reports
        WHERE id = ?
        """,
        (report_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"No report with id {report_id}")
    return FiledReport(
        id=row["id"],
        name=row["name"],
        station=row["station"],
        wind=Decimal(row["wind"]),
        temperature=Decimal(row["temperature"]),
        fuel=Decimal(row["fuel"]),
        note=row["note"],
    )


def read_created_at(connection: sqlite3.Connection, report_id: int) -> datetime:
    """Return the UTC filing time stored for one report."""
    row = connection.execute(
        "SELECT created_at FROM reports WHERE id = ?",
        (report_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"No report with id {report_id}")
    return datetime.fromisoformat(row["created_at"])


def update_launch_verdict(
    connection: sqlite3.Connection,
    report_id: int,
    *,
    verdict: str,
    broken_limits: tuple[str, ...],
    model_seriousness: str,
    deadline_seriousness: str,
    deadline_minutes: int,
    due_at: datetime,
) -> None:
    """Store the limit check and the deadline on one saved report."""
    cursor = connection.execute(
        """
        UPDATE reports
        SET verdict = ?,
            broken_limits = ?,
            model_seriousness = ?,
            deadline_seriousness = ?,
            deadline_minutes = ?,
            due_at = ?
        WHERE id = ?
        """,
        (
            verdict,
            json.dumps(list(broken_limits)),
            model_seriousness,
            deadline_seriousness,
            deadline_minutes,
            due_at.isoformat(),
            report_id,
        ),
    )
    if cursor.rowcount != 1:
        raise LookupError(f"No report with id {report_id}")


def list_console_reports(connection: sqlite3.Connection) -> list[ConsoleReport]:
    """Return saved reports, newest filing first."""
    rows = connection.execute(
        """
        SELECT id, name, station, wind, temperature, fuel, note,
               verdict, broken_limits, deadline_minutes, due_at
        FROM reports
        ORDER BY created_at DESC, id DESC
        """
    ).fetchall()
    return [_console_report(row) for row in rows]


def read_console_report(connection: sqlite3.Connection, report_id: int) -> ConsoleReport:
    """Read one report for the console detail page."""
    row = connection.execute(
        """
        SELECT id, name, station, wind, temperature, fuel, note,
               verdict, broken_limits, deadline_minutes, due_at
        FROM reports
        WHERE id = ?
        """,
        (report_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"No report with id {report_id}")
    return _console_report(row)


def _console_report(row: sqlite3.Row) -> ConsoleReport:
    return ConsoleReport(
        id=row["id"],
        name=row["name"],
        station=row["station"],
        wind=row["wind"],
        temperature=row["temperature"],
        fuel=row["fuel"],
        note=row["note"],
        verdict=row["verdict"],
        broken_limits=_parse_broken_limits(row["broken_limits"]),
        deadline_minutes=row["deadline_minutes"],
        due_at=row["due_at"],
    )


def _parse_broken_limits(stored: str | None) -> tuple[str, ...]:
    if stored is None or stored == "":
        return ()
    parsed = json.loads(stored)
    if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
        raise ValueError("Broken limits must be a list of names")
    return tuple(parsed)


def _store_decimal(value: Decimal | str | float) -> str:
    return format(_as_decimal(value), "f")


def _as_decimal(value: Decimal | str | float) -> Decimal:
    if isinstance(value, bool):
        raise TypeError("A reading must be a decimal number")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, (int, str)):
        return Decimal(value)
    raise TypeError("A reading must be a decimal number")
