import os

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.model_client import (
    FAILURE_INVALID,
    TASK_REVIEW,
    TASK_SORT,
    AzureFoundryClient,
    FakeModelClient,
    Unreachable,
)
from app.pipeline import run_pipeline
from tests.support import ENV_NAMES, legal_facts, make_client, only_row, payload


def test_fake_returns_the_script_and_records_the_prompt():
    fake = FakeModelClient(
        scripts={
            TASK_SORT: {"vehicle_part": "avionics", "seriousness": "high"},
            TASK_REVIEW: [
                {"accepted": False, "feedback": "first"},
                {"accepted": True, "feedback": ""},
            ],
        }
    )

    sort = fake.complete(TASK_SORT, "system text", "user text", {"vehicle_part": "string"})
    first = fake.complete(TASK_REVIEW, "review system", "review user", {"accepted": "boolean"})
    second = fake.complete(TASK_REVIEW, "review system", "again", {"accepted": "boolean"})
    invalid = FakeModelClient(scripts={TASK_SORT: "{not json"}).complete(
        TASK_SORT,
        "system text",
        "user text",
        {},
    )

    assert sort.failure is None
    assert sort.parsed == {"vehicle_part": "avionics", "seriousness": "high"}
    assert first.parsed["feedback"] == "first"
    assert second.parsed["accepted"] is True
    assert invalid.failure == FAILURE_INVALID
    assert invalid.parsed is None
    assert fake.calls[0].system == "system text"
    assert fake.calls[0].user == "user text"
    assert fake.calls[0].task == TASK_SORT
    assert [call.task for call in fake.calls].count(TASK_REVIEW) == 2


def test_fake_pipeline_does_not_read_the_api_key_or_build_the_azure_client(monkeypatch):
    monkeypatch.setenv("AZURE_FOUNDRY_API_KEY", "super-secret-key")
    reads: list[str] = []
    real_get = os.environ.get

    def spy_get(key, default=None):
        if key == "AZURE_FOUNDRY_API_KEY":
            reads.append(key)
        return real_get(key, default)

    monkeypatch.setattr(os.environ, "get", spy_get)
    constructed: list[str] = []

    def spy_init(self, *args, **kwargs):
        constructed.append("built")
        raise AssertionError("Azure client should not be built")

    monkeypatch.setattr(AzureFoundryClient, "__init__", spy_init)
    fake = FakeModelClient()

    result = run_pipeline(fake, legal_facts(note="Gust at the pad."))

    assert result.status == "pending_approval"
    assert constructed == []
    assert reads == []
    recorded = "\n".join(call.system + "\n" + call.user for call in fake.calls)
    assert "super-secret-key" not in recorded
    assert "AZURE_FOUNDRY_API_KEY" not in recorded
    assert "Gust at the pad." in recorded
    assert "The launch verdict is already decided by code." in recorded


@pytest.mark.parametrize("backend", ["", "fake", "FAKE"])
def test_the_app_does_not_build_the_azure_client(monkeypatch, tmp_path, backend):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "mission-control.sqlite"))
    monkeypatch.setenv("AZURE_FOUNDRY_API_KEY", "super-secret-key")
    if backend:
        monkeypatch.setenv("MODEL_BACKEND", backend)
    constructed: list[str] = []

    class Boom:
        def __init__(self, *args, **kwargs):
            constructed.append("built")
            raise AssertionError("Azure client should not be built")

    monkeypatch.setattr("app.model_client.AzureFoundryClient", Boom)
    client = TestClient(create_app())

    response = client.post("/", data=payload(note="Gust at the pad."))
    detail = client.get("/console/1")

    assert response.status_code == 200
    assert constructed == []
    assert "super-secret-key" not in response.text
    assert "super-secret-key" not in detail.text


def test_unreachable_sort_skips_later_calls_and_keeps_the_verdict(monkeypatch, tmp_path):
    database_path = tmp_path / "mission-control.sqlite"
    fake = FakeModelClient(scripts={TASK_SORT: Unreachable()})
    client = make_client(monkeypatch, database_path)
    client.app.state.model_client = fake

    filed = client.post(
        "/",
        data=payload(wind="25.1", note="The service is down."),
    )
    row = only_row(database_path)
    detail = client.get(f"/console/{row['id']}")

    assert filed.status_code == 200
    assert [call.task for call in fake.calls] == [TASK_SORT]
    assert row["verdict"] == "no_go"
    assert row["status"] == "incomplete"
    assert row["model_seriousness"] is None
    assert row["briefing"] is None
    assert row["approver_name"] is None
    assert "Verdict: no_go" in detail.text
    assert ">Approve</button>" not in detail.text
