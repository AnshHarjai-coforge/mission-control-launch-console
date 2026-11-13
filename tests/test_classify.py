import json

from app.classify import (
    STAND_IN_PART,
    STAND_IN_SERIOUSNESS,
    classify_report,
    interpret_sort,
)
from app.model_client import TASK_SORT, FakeModelClient, ModelResponse
from app.pipeline import run_pipeline
from tests.support import legal_facts, make_client, only_row, payload


def test_a_valid_sort_is_kept():
    result = _sort({"vehicle_part": "ground support", "seriousness": "high"})

    assert result.vehicle_part == "ground support"
    assert result.vehicle_part_stand_in is False
    assert result.model_seriousness == "high"


def test_other_is_a_real_answer():
    result = _sort({"vehicle_part": "other", "seriousness": "low"})

    assert result.vehicle_part == "other"
    assert result.vehicle_part_stand_in is False
    assert result.model_seriousness == "low"


def test_whitespace_around_a_listed_part_is_kept():
    result = _sort({"vehicle_part": " weather ", "seriousness": " low "})

    assert result.vehicle_part == "weather"
    assert result.vehicle_part_stand_in is False
    assert result.model_seriousness == "low"


def test_an_unknown_part_is_replaced_and_a_valid_seriousness_is_kept():
    result = _sort({"vehicle_part": "engine", "seriousness": "high"})

    assert result.vehicle_part == STAND_IN_PART
    assert result.vehicle_part_stand_in is True
    assert result.model_seriousness == "high"


def test_an_unknown_seriousness_is_replaced_and_a_valid_part_is_kept():
    result = _sort({"vehicle_part": "propulsion", "seriousness": "severe"})

    assert result.vehicle_part == "propulsion"
    assert result.vehicle_part_stand_in is False
    assert result.model_seriousness == STAND_IN_SERIOUSNESS


def test_not_specified_is_not_a_model_choice():
    result = _sort({"vehicle_part": "not specified", "seriousness": "low"})

    assert result.vehicle_part == STAND_IN_PART
    assert result.vehicle_part_stand_in is True
    assert result.model_seriousness == "low"


def test_a_non_json_answer_is_replaced():
    fake = FakeModelClient(scripts={TASK_SORT: "not json"})

    result = classify_report(fake, legal_facts())

    assert result.vehicle_part == STAND_IN_PART
    assert result.vehicle_part_stand_in is True
    assert result.model_seriousness == STAND_IN_SERIOUSNESS
    assert result.unreachable is False


def test_a_missing_answer_is_replaced():
    result = _sort({})

    assert result.vehicle_part == STAND_IN_PART
    assert result.vehicle_part_stand_in is True
    assert result.model_seriousness == STAND_IN_SERIOUSNESS


def test_extra_verdict_fields_are_ignored_by_the_sort():
    response = ModelResponse(
        parsed={
            "vehicle_part": "avionics",
            "seriousness": "medium",
            "verdict": "go",
            "status": "approved",
        },
        raw_text="{}",
        input_tokens=1,
        output_tokens=1,
        failure=None,
    )

    result = interpret_sort(response)

    assert result.vehicle_part == "avionics"
    assert result.model_seriousness == "medium"


def test_high_with_no_broken_limit_is_due_in_five_minutes():
    fake = FakeModelClient(
        scripts={TASK_SORT: {"vehicle_part": "range safety", "seriousness": "high"}}
    )

    result = run_pipeline(fake, legal_facts())

    assert result.model_seriousness == "high"
    assert result.deadline_seriousness == "high"
    assert result.deadline_minutes == 5
    assert result.status == "pending_approval"


def test_a_replaced_sort_does_not_change_the_verdict(monkeypatch, tmp_path):
    database_path = tmp_path / "mission-control.sqlite"
    fake = FakeModelClient(scripts={TASK_SORT: "not json"})
    client = make_client(monkeypatch, database_path)
    client.app.state.model_client = fake

    client.post(
        "/",
        data=payload(wind="25.1", temperature="4", fuel="98", note="Not json from the model."),
    )
    row = only_row(database_path)
    detail = client.get(f"/console/{row['id']}")

    assert row["verdict"] == "no_go"
    assert json.loads(row["broken_limits"]) == ["wind_knots"]
    assert row["vehicle_part"] == "not specified"
    assert row["vehicle_part_stand_in"] == 1
    assert row["model_seriousness"] == "medium"
    assert row["deadline_seriousness"] == "high"
    assert row["deadline_minutes"] == 5
    assert row["status"] != "approved"
    assert "Model said: medium" in detail.text
    assert "Deadline uses: high" in detail.text
    assert "Verdict: no_go" in detail.text


def test_medium_on_a_legal_report_is_due_in_fifteen_minutes(monkeypatch, tmp_path):
    database_path = tmp_path / "mission-control.sqlite"
    fake = FakeModelClient(
        scripts={TASK_SORT: {"vehicle_part": "avionics", "seriousness": "medium"}}
    )
    client = make_client(monkeypatch, database_path)
    client.app.state.model_client = fake

    client.post("/", data=payload(note="Avionics looks medium."))
    row = only_row(database_path)
    detail = client.get(f"/console/{row['id']}")

    assert row["verdict"] == "go"
    assert json.loads(row["broken_limits"]) == []
    assert row["vehicle_part"] == "avionics"
    assert row["vehicle_part_stand_in"] == 0
    assert row["model_seriousness"] == "medium"
    assert row["deadline_seriousness"] == "medium"
    assert row["deadline_minutes"] == 15
    assert "Model said: medium" in detail.text
    assert "Deadline uses: medium" in detail.text
    assert "Deadline: 15 minutes" in detail.text


def test_low_with_a_broken_limit_still_uses_high_for_the_deadline(monkeypatch, tmp_path):
    database_path = tmp_path / "mission-control.sqlite"
    fake = FakeModelClient(
        scripts={
            TASK_SORT: {
                "vehicle_part": "weather",
                "seriousness": "low",
                "verdict": "go",
                "status": "approved",
            }
        }
    )
    client = make_client(monkeypatch, database_path)
    client.app.state.model_client = fake

    client.post("/", data=payload(wind="40.2", temperature="20", fuel="99", note="Just a small gust."))
    row = only_row(database_path)
    detail = client.get(f"/console/{row['id']}")

    assert row["verdict"] == "no_go"
    assert json.loads(row["broken_limits"]) == ["wind_knots"]
    assert row["model_seriousness"] == "low"
    assert row["deadline_seriousness"] == "high"
    assert row["deadline_minutes"] == 5
    assert row["status"] == "pending_approval"
    assert row["approver_name"] is None
    assert "Model said: low" in detail.text
    assert "Deadline uses: high" in detail.text
    assert "Verdict: no_go" in detail.text


def _sort(answer: dict):
    fake = FakeModelClient(scripts={TASK_SORT: answer})
    return classify_report(fake, legal_facts())
