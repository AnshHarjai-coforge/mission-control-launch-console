from datetime import datetime, timedelta
from decimal import Decimal

from app.db import insert_report, open_database, read_report

_UNSET_REPORT_COLUMNS = (
    "verdict",
    "broken_limits",
    "vehicle_part",
    "vehicle_part_stand_in",
    "model_seriousness",
    "deadline_seriousness",
    "deadline_minutes",
    "due_at",
    "category",
    "hidden_instruction",
    "hidden_instruction_reason",
    "missing_information",
    "missing_information_reason",
    "panic",
    "panic_reason",
    "briefing",
    "rounds_run",
    "last_review_accepted",
    "last_review_comment",
    "status",
    "approved_at",
    "approver_name",
    "total_cost",
)

_REPORT_COLUMNS = {
    "id",
    "created_at",
    "name",
    "station",
    "wind",
    "temperature",
    "fuel",
    "note",
    *_UNSET_REPORT_COLUMNS,
}

_TRACE_STEP_COLUMNS = {
    "id",
    "report_id",
    "step_order",
    "name",
    "kind",
    "round_number",
    "input_tokens",
    "output_tokens",
    "cost",
    "outcome",
    "detail",
}


def test_filed_report_round_trips_after_the_connection_closes(tmp_path):
    database_path = tmp_path / "mission-control.sqlite"
    connection = open_database(database_path)
    report_id = insert_report(
        connection,
        name="A. Rivera",
        station="Weather",
        wind=Decimal("25.1"),
        temperature=Decimal("18.5"),
        fuel=Decimal("99.5"),
        note="Gust at the pad.",
    )
    connection.close()

    reopened = open_database(database_path)
    try:
        report = read_report(reopened, report_id)
        stored = reopened.execute(
            "SELECT * FROM reports WHERE id = ?",
            (report_id,),
        ).fetchone()
        trace_count = reopened.execute(
            "SELECT COUNT(*) AS n FROM trace_steps"
        ).fetchone()["n"]
    finally:
        reopened.close()

    assert report.name == "A. Rivera"
    assert report.station == "Weather"
    assert report.wind == Decimal("25.1")
    assert report.temperature == Decimal("18.5")
    assert report.fuel == Decimal("99.5")
    assert report.note == "Gust at the pad."
    assert stored["wind"] == "25.1"
    assert stored["temperature"] == "18.5"
    assert stored["fuel"] == "99.5"
    created_at = datetime.fromisoformat(stored["created_at"])
    assert created_at.utcoffset() == timedelta(0)
    for column in _UNSET_REPORT_COLUMNS:
        assert stored[column] is None
    assert trace_count == 0


def test_saved_tables_include_every_column(tmp_path):
    connection = open_database(tmp_path / "mission-control.sqlite")
    try:
        assert _column_names(connection, "reports") == _REPORT_COLUMNS
        assert _column_names(connection, "trace_steps") == _TRACE_STEP_COLUMNS
    finally:
        connection.close()


def test_open_database_creates_a_missing_parent_folder(tmp_path):
    database_path = tmp_path / "data" / "mission-control.sqlite"
    connection = open_database(database_path)
    connection.close()

    assert database_path.is_file()


def _column_names(connection, table: str) -> set[str]:
    if table not in {"reports", "trace_steps"}:
        raise AssertionError(table)
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return {row["name"] for row in rows}
