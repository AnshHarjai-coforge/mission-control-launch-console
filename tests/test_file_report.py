import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import open_database, read_report
from app.main import create_app
from app.model_client import DEFAULT_BRIEFING_SUMMARY, DEFAULT_CHECK_REASON

_ENV_NAMES = (
    "DATABASE_PATH",
    "MODEL_BACKEND",
    "AZURE_FOUNDRY_BASE_URL",
    "AZURE_FOUNDRY_API_KEY",
    "AZURE_FOUNDRY_MODEL",
    "INPUT_USD_PER_MILLION",
    "OUTPUT_USD_PER_MILLION",
    "MODEL_TIMEOUT_SECONDS",
)

_FIELDS = ("name", "station", "wind", "temperature", "fuel", "note")
_READING_FIELDS = ("wind", "temperature", "fuel")


def test_filing_page_lists_every_field(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path / "mission-control.sqlite")
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    for field in _FIELDS:
        assert f'name="{field}"' in response.text
    assert not (tmp_path / "mission-control.sqlite").exists()


def test_valid_report_is_saved_and_readable_from_a_new_connection(monkeypatch, tmp_path):
    database_path = tmp_path / "mission-control.sqlite"
    client = _client(monkeypatch, database_path)
    payload = _valid_payload()

    response = client.post("/", data=payload)

    assert response.status_code == 200
    assert "Report filed." in response.text
    for value in payload.values():
        assert value in response.text
    report, row = _read_saved(database_path)
    assert report.name == "A. Rivera"
    assert report.station == "Weather"
    assert report.wind == Decimal("25.1")
    assert report.temperature == Decimal("18.5")
    assert report.fuel == Decimal("99.5")
    assert report.note == "Gust at the pad."
    assert row["wind"] == "25.1"
    assert row["temperature"] == "18.5"
    assert row["fuel"] == "99.5"
    assert f'href="/console/{report.id}"' in response.text
    _assert_no_go_for_wind(row)
    _assert_default_pipeline(row)
    _assert_no_trace_steps(database_path)
    assert client.app.state.settings.azure_foundry_api_key == ""


def test_wind_outside_the_launch_limit_is_saved_as_no_go(monkeypatch, tmp_path):
    database_path = tmp_path / "mission-control.sqlite"
    client = _client(monkeypatch, database_path)
    payload = _valid_payload()
    payload["wind"] = "40"

    response = client.post("/", data=payload)

    assert response.status_code == 200
    assert "Report filed." in response.text
    report, row = _read_saved(database_path)
    assert report.wind == Decimal(40)
    assert report.name == payload["name"]
    assert report.station == payload["station"]
    assert report.temperature == Decimal(payload["temperature"])
    assert report.fuel == Decimal(payload["fuel"])
    assert report.note == payload["note"]
    assert row["wind"] == "40"
    _assert_no_go_for_wind(row)
    _assert_default_pipeline(row)


def test_maximum_lengths_are_saved(monkeypatch, tmp_path):
    database_path = tmp_path / "mission-control.sqlite"
    client = _client(monkeypatch, database_path)
    payload = _valid_payload()
    payload["name"] = "N" * 80
    payload["station"] = "S" * 80
    payload["note"] = "x" * 4000

    response = client.post("/", data=payload)

    assert response.status_code == 200
    assert "Report filed." in response.text
    report, row = _read_saved(database_path)
    assert report.name == "N" * 80
    assert report.station == "S" * 80
    assert report.note == "x" * 4000
    assert report.wind == Decimal("25.1")
    assert report.temperature == Decimal("18.5")
    assert report.fuel == Decimal("99.5")
    _assert_no_go_for_wind(row)
    _assert_default_pipeline(row)


@pytest.mark.parametrize("field", _FIELDS)
@pytest.mark.parametrize("blank", ["", "   ", "\n\t "])
def test_blank_field_is_rejected(monkeypatch, tmp_path, field, blank):
    database_path = tmp_path / "mission-control.sqlite"
    client = _client(monkeypatch, database_path)
    payload = _valid_payload()
    payload[field] = blank

    response = client.post("/", data=payload)

    assert response.status_code == 400
    assert f"{field} is blank." in response.text
    assert _saved_rows(database_path) == []


def test_every_blank_field_is_named(monkeypatch, tmp_path):
    database_path = tmp_path / "mission-control.sqlite"
    client = _client(monkeypatch, database_path)

    response = client.post("/", data={field: " \n\t " for field in _FIELDS})

    assert response.status_code == 400
    for field in _FIELDS:
        assert f"{field} is blank." in response.text
    assert "must be a number" not in response.text
    assert _saved_rows(database_path) == []


def test_whitespace_longer_than_the_name_limit_is_blank(monkeypatch, tmp_path):
    database_path = tmp_path / "mission-control.sqlite"
    client = _client(monkeypatch, database_path)
    payload = _valid_payload()
    payload["name"] = " " * 81

    response = client.post("/", data=payload)

    assert response.status_code == 400
    assert "name is blank." in response.text
    assert "name is too long." not in response.text
    assert _saved_rows(database_path) == []


@pytest.mark.parametrize("field", _READING_FIELDS)
def test_non_number_is_rejected(monkeypatch, tmp_path, field):
    database_path = tmp_path / "mission-control.sqlite"
    client = _client(monkeypatch, database_path)
    payload = _valid_payload()
    payload[field] = "not-a-number"

    response = client.post("/", data=payload)

    assert response.status_code == 400
    assert f"{field} must be a number." in response.text
    assert _saved_rows(database_path) == []


def test_every_non_number_is_named(monkeypatch, tmp_path):
    database_path = tmp_path / "mission-control.sqlite"
    client = _client(monkeypatch, database_path)
    payload = _valid_payload()
    for field in _READING_FIELDS:
        payload[field] = "not-a-number"

    response = client.post("/", data=payload)

    assert response.status_code == 400
    for field in _READING_FIELDS:
        assert f"{field} must be a number." in response.text
    assert _saved_rows(database_path) == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", "N" * 81),
        ("station", "S" * 81),
        ("note", "x" * 4001),
    ],
)
def test_over_length_field_is_rejected(monkeypatch, tmp_path, field, value):
    database_path = tmp_path / "mission-control.sqlite"
    client = _client(monkeypatch, database_path)
    payload = _valid_payload()
    payload[field] = value

    response = client.post("/", data=payload)

    assert response.status_code == 400
    assert f"{field} is too long." in response.text
    assert _saved_rows(database_path) == []


def test_over_length_fields_are_all_named(monkeypatch, tmp_path):
    database_path = tmp_path / "mission-control.sqlite"
    client = _client(monkeypatch, database_path)
    payload = _valid_payload()
    payload["name"] = "N" * 81
    payload["station"] = "S" * 81
    payload["note"] = "x" * 4001

    response = client.post("/", data=payload)

    assert response.status_code == 400
    assert "name is too long." in response.text
    assert "station is too long." in response.text
    assert "note is too long." in response.text
    assert _saved_rows(database_path) == []


def test_submitted_values_are_shown_as_text(monkeypatch, tmp_path):
    database_path = tmp_path / "mission-control.sqlite"
    client = _client(monkeypatch, database_path)
    payload = _valid_payload()
    payload["name"] = "<b>Ada</b>"
    payload["station"] = "<i>Pad</i>"
    payload["note"] = "<script>alert(1)</script>"

    response = client.post("/", data=payload)

    assert response.status_code == 200
    assert "<b>" not in response.text
    assert "<i>" not in response.text
    assert "<script>" not in response.text
    assert "&lt;b&gt;Ada&lt;/b&gt;" in response.text
    assert "&lt;i&gt;Pad&lt;/i&gt;" in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text
    report, _row = _read_saved(database_path)
    assert report.name == "<b>Ada</b>"
    assert report.station == "<i>Pad</i>"
    assert report.note == "<script>alert(1)</script>"


def test_rejected_values_are_not_written_as_html(monkeypatch, tmp_path):
    database_path = tmp_path / "mission-control.sqlite"
    client = _client(monkeypatch, database_path)
    payload = _valid_payload()
    payload["name"] = ""
    payload["note"] = "<script>alert(1)</script>"

    response = client.post("/", data=payload)

    assert response.status_code == 400
    assert "name is blank." in response.text
    assert "<script>" not in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text
    assert _saved_rows(database_path) == []


@pytest.mark.parametrize("raw_path", ["", "   ", "\n"])
def test_blank_database_path_uses_the_default_file(monkeypatch, tmp_path, raw_path):
    default_path = Path("data") / "mission-control.sqlite"
    existed = default_path.exists()
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABASE_PATH", raw_path)
    opened: list[str | None] = []

    def open_temporary(path=None):
        opened.append(path)
        return open_database(tmp_path / "stand-in.sqlite")

    monkeypatch.setattr("app.main.open_database", open_temporary)
    client = TestClient(create_app())

    response = client.post("/", data=_valid_payload())

    assert response.status_code == 200
    assert opened == [None]
    if not existed:
        assert not default_path.exists()


def test_requests_do_not_create_the_default_database(monkeypatch, tmp_path):
    database_path = tmp_path / "mission-control.sqlite"
    default_path = Path("data") / "mission-control.sqlite"
    already_there = default_path.exists()
    client = _client(monkeypatch, database_path)

    assert client.get("/").status_code == 200
    assert client.get("/health").status_code == 200
    assert client.get("/console").status_code == 200
    assert client.post("/", data=_valid_payload()).status_code == 200
    rejected = _valid_payload()
    rejected["fuel"] = "not-a-number"
    assert client.post("/", data=rejected).status_code == 400

    if not already_there:
        assert not default_path.exists()
    assert database_path.is_file()


def _client(monkeypatch, database_path: Path) -> TestClient:
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABASE_PATH", str(database_path))
    client = TestClient(create_app())
    assert client.app.state.settings.database_path == str(database_path)
    assert client.app.state.settings.azure_foundry_api_key == ""
    return client


def _valid_payload() -> dict[str, str]:
    return {
        "name": "A. Rivera",
        "station": "Weather",
        "wind": "25.1",
        "temperature": "18.5",
        "fuel": "99.5",
        "note": "Gust at the pad.",
    }


def _read_saved(database_path: Path):
    first = open_database(database_path)
    first.close()
    reopened = open_database(database_path)
    try:
        rows = reopened.execute("SELECT * FROM reports").fetchall()
        assert len(rows) == 1
        return read_report(reopened, rows[0]["id"]), rows[0]
    finally:
        reopened.close()


def _saved_rows(database_path: Path) -> list:
    if not database_path.exists():
        return []
    connection = open_database(database_path)
    try:
        return list(connection.execute("SELECT * FROM reports").fetchall())
    finally:
        connection.close()


def _assert_default_pipeline(row) -> None:
    assert row["vehicle_part"] == "weather"
    assert row["vehicle_part_stand_in"] == 0
    assert row["category"] == "report"
    assert row["hidden_instruction"] == 0
    assert row["hidden_instruction_reason"] == DEFAULT_CHECK_REASON
    assert row["missing_information"] == 0
    assert row["missing_information_reason"] == DEFAULT_CHECK_REASON
    assert row["panic"] == 0
    assert row["panic_reason"] == DEFAULT_CHECK_REASON
    assert row["briefing"] == DEFAULT_BRIEFING_SUMMARY
    assert row["rounds_run"] == 1
    assert row["last_review_accepted"] == 1
    assert row["last_review_comment"] == ""
    assert row["status"] == "pending_approval"
    assert row["approved_at"] is None
    assert row["approver_name"] is None
    assert row["total_cost"] is None


def _assert_no_trace_steps(database_path: Path) -> None:
    connection = open_database(database_path)
    try:
        count = connection.execute("SELECT COUNT(*) AS n FROM trace_steps").fetchone()["n"]
    finally:
        connection.close()
    assert count == 0


def _assert_no_go_for_wind(row) -> None:
    assert row["verdict"] == "no_go"
    assert json.loads(row["broken_limits"]) == ["wind_knots"]
    assert row["model_seriousness"] == "low"
    assert row["deadline_seriousness"] == "high"
    assert row["deadline_minutes"] == 5
    created_at = datetime.fromisoformat(row["created_at"])
    due_at = datetime.fromisoformat(row["due_at"])
    assert created_at.utcoffset() == timedelta(0)
    assert due_at - created_at == timedelta(minutes=5)
