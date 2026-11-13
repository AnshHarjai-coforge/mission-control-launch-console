from app.model_client import TASK_DRAFT, TASK_REVIEW, TASK_SORT, FakeModelClient
from tests.support import make_client, only_row, payload

_LOW_SORT = {"vehicle_part": "weather", "seriousness": "low", "status": "approved"}


def test_round_one_comment_is_in_the_round_two_prompt(monkeypatch, tmp_path):
    comment = 'Keep the phrase "pad 4" & the station.'
    fake = FakeModelClient(
        scripts={
            TASK_SORT: _LOW_SORT,
            TASK_DRAFT: [_draft("FIRST DRAFT"), _draft("SECOND DRAFT")],
            TASK_REVIEW: [
                {"accepted": False, "feedback": comment},
                {"accepted": True, "feedback": ""},
            ],
        }
    )
    client, row = _file(monkeypatch, tmp_path, fake)
    drafts = [call for call in fake.calls if call.task == TASK_DRAFT]
    reviews = [call for call in fake.calls if call.task == TASK_REVIEW]
    detail = client.get(f"/console/{row['id']}")

    assert len(drafts) == 2
    assert len(reviews) == 2
    assert f"Previous comment:\n{comment}" in drafts[1].user
    assert comment not in drafts[0].user
    assert row["briefing"] == "SECOND DRAFT"
    assert row["rounds_run"] == 2
    assert row["last_review_accepted"] == 1
    assert row["status"] == "pending_approval"
    assert "Briefing: SECOND DRAFT" in detail.text


def test_yes_on_round_one_skips_round_two(monkeypatch, tmp_path):
    fake = FakeModelClient(
        scripts={
            TASK_SORT: _LOW_SORT,
            TASK_DRAFT: [_draft("FIRST"), _draft("SECOND")],
            TASK_REVIEW: [
                {"accepted": True, "feedback": "", "status": "approved"},
                {"accepted": False, "feedback": "should not run"},
            ],
        }
    )
    _, row = _file(monkeypatch, tmp_path, fake)

    assert [call.task for call in fake.calls].count(TASK_DRAFT) == 1
    assert [call.task for call in fake.calls].count(TASK_REVIEW) == 1
    assert row["briefing"] == "FIRST"
    assert row["rounds_run"] == 1
    assert row["last_review_accepted"] == 1
    assert row["status"] == "pending_approval"
    assert row["approver_name"] is None


def test_three_no_answers_keep_the_last_draft_unapproved(monkeypatch, tmp_path):
    summaries = ["ROUND-ONE-SUMMARY", "ROUND-TWO-SUMMARY", "ROUND-THREE-SUMMARY"]
    comments = ["COMMENT-FROM-ROUND-ONE", "COMMENT-FROM-ROUND-TWO", "COMMENT-FROM-ROUND-THREE"]
    fake = FakeModelClient(
        scripts={
            TASK_SORT: _LOW_SORT,
            TASK_DRAFT: [_draft(summary, status="approved") for summary in summaries],
            TASK_REVIEW: [
                {"accepted": False, "feedback": comment, "status": "approved"}
                for comment in comments
            ],
        }
    )
    client, row = _file(monkeypatch, tmp_path, fake)
    drafts = [call for call in fake.calls if call.task == TASK_DRAFT]
    reviews = [call for call in fake.calls if call.task == TASK_REVIEW]
    detail = client.get(f"/console/{row['id']}")

    assert len(drafts) == 3
    assert len(reviews) == 3
    assert comments[0] in drafts[1].user
    assert comments[1] in drafts[2].user
    assert row["briefing"] == "ROUND-THREE-SUMMARY"
    assert row["rounds_run"] == 3
    assert row["last_review_accepted"] == 0
    assert row["status"] == "pending_approval"
    assert row["approver_name"] is None
    assert "Briefing: ROUND-THREE-SUMMARY" in detail.text
    assert "ROUND-ONE-SUMMARY" not in detail.text
    assert ">Approve</button>" in detail.text


def test_a_disagreeing_verdict_is_not_the_paragraph_on_screen(monkeypatch, tmp_path):
    fake = FakeModelClient(
        scripts={
            TASK_SORT: _LOW_SORT,
            TASK_DRAFT: [
                {
                    "summary": "PARAGRAPH-DISAGREES-WITH-CODE",
                    "verdict": "no_go",
                    "violations": ["wind_knots"],
                    "brief_by_minutes": 5,
                    "status": "approved",
                },
                _draft("PARAGRAPH-MATCHES-THE-CODE"),
            ],
            TASK_REVIEW: [{"accepted": True, "feedback": ""}],
        }
    )
    client, row = _file(monkeypatch, tmp_path, fake)
    drafts = [call for call in fake.calls if call.task == TASK_DRAFT]
    detail = client.get(f"/console/{row['id']}")

    assert "The draft verdict does not match the code verdict go." in drafts[1].user
    assert row["verdict"] == "go"
    assert row["briefing"] == "PARAGRAPH-MATCHES-THE-CODE"
    assert row["status"] == "pending_approval"
    assert "Briefing: PARAGRAPH-MATCHES-THE-CODE" in detail.text
    assert "PARAGRAPH-DISAGREES-WITH-CODE" not in detail.text
    assert "Verdict: go" in detail.text
    assert "Verdict: no_go" not in detail.text


def _draft(summary: str, **extra: object) -> dict:
    body: dict[str, object] = {
        "summary": summary,
        "verdict": "go",
        "violations": [],
        "brief_by_minutes": 30,
    }
    body.update(extra)
    return body


def _file(monkeypatch, tmp_path, fake: FakeModelClient):
    database_path = tmp_path / "mission-control.sqlite"
    client = make_client(monkeypatch, database_path)
    client.app.state.model_client = fake
    response = client.post("/", data=payload())
    assert response.status_code == 200
    return client, only_row(database_path)
