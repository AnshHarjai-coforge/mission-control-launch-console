"""Shared fixtures for the model-pipeline tests."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from app.db import open_database
from app.facts import ReportFacts
from app.main import create_app

ENV_NAMES = (
    "DATABASE_PATH",
    "MODEL_BACKEND",
    "AZURE_FOUNDRY_BASE_URL",
    "AZURE_FOUNDRY_API_KEY",
    "AZURE_FOUNDRY_MODEL",
    "INPUT_USD_PER_MILLION",
    "OUTPUT_USD_PER_MILLION",
    "MODEL_TIMEOUT_SECONDS",
)


def make_client(monkeypatch, database_path: Path) -> TestClient:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABASE_PATH", str(database_path))
    return TestClient(create_app())


def payload(**overrides: str) -> dict[str, str]:
    body = {
        "name": "A. Rivera",
        "station": "Weather",
        "wind": "25",
        "temperature": "4",
        "fuel": "98",
        "note": "Nominal.",
    }
    body.update(overrides)
    return body


def rows(database_path: Path) -> list:
    connection = open_database(database_path)
    try:
        return list(connection.execute("SELECT * FROM reports ORDER BY id").fetchall())
    finally:
        connection.close()


def only_row(database_path: Path):
    stored = rows(database_path)
    assert len(stored) == 1
    return stored[0]


def legal_facts(
    *,
    note: str = "Nominal.",
    filed_at: datetime | None = None,
) -> ReportFacts:
    return ReportFacts(
        name="A. Rivera",
        station="Weather",
        wind=Decimal(25),
        temperature=Decimal(4),
        fuel=Decimal(98),
        note=note,
        verdict="go",
        broken_limits=(),
        filed_at=filed_at or datetime(2026, 11, 13, 15, 0, tzinfo=UTC),
    )
