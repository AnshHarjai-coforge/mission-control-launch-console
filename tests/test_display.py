import re
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.display import board_tally, due_label, meter_width, utc_stamp
from app.main import create_app

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


def test_utc_stamp_reads_as_a_clock():
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}  \d{2}:\d{2}:\d{2} UTC", utc_stamp())


def test_due_label_drops_the_fractional_seconds():
    assert due_label("2026-11-16T20:45:09.421709+00:00") == "2026-11-16 20:45 UTC"
    assert due_label(None) == ""
    assert due_label("") == ""
    assert due_label("not-a-time") == "not-a-time"


def test_meter_width_clamps_each_scale():
    assert meter_width("12.5", "wind") == "50%"
    assert meter_width("25", "wind") == "100%"
    assert meter_width("25.1", "wind") == "100%"
    assert meter_width("-1", "wind") == "0%"
    assert meter_width("4", "temperature") == "10%"
    assert meter_width("3.9", "temperature") == "9%"
    assert meter_width("98", "fuel") == "80%"
    assert meter_width("100", "fuel") == "100%"
    assert meter_width("97.9", "fuel") == "79%"
    assert meter_width("89", "fuel") == "0%"
    assert meter_width("NaN", "wind") == "0%"
    assert meter_width("not-a-number", "wind") == "0%"
    assert meter_width("10", "other") == "0%"


def test_board_tally_keeps_a_spam_go_off_the_go_count():
    reports = [SimpleNamespace(verdict="go", status="pending_approval")]
    spam = [SimpleNamespace(verdict="go", status="approved")]
    outside = SimpleNamespace(verdict="no_go", status="pending_approval")

    tally = board_tally([*reports, outside], spam)

    assert tally == {"go": 1, "nogo": 1, "awaiting": 2, "spam": 1}


def test_pages_share_the_console_shell(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path / "mission-control.sqlite")

    for path in ("/", "/console", "/health"):
        page = client.get(path)
        assert page.status_code == 200
        assert "/static/console.css" in page.text
        assert "<script>" not in page.text

    console = client.get("/console")
    assert "No reports." in console.text
    assert "no_go" not in console.text
    assert "ok" in client.get("/health").text
    style = client.get("/static/console.css")
    assert style.status_code == 200
    assert ".step-card" in style.text


def _client(monkeypatch, database_path) -> TestClient:
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABASE_PATH", str(database_path))
    return TestClient(create_app())
