from datetime import UTC, datetime, timedelta

import pytest

from app.brief_by import brief_by


@pytest.mark.parametrize(
    ("seriousness", "minutes"),
    [("high", 5), ("medium", 15), ("low", 30)],
)
def test_no_broken_limit_uses_the_model_seriousness(seriousness, minutes):
    filed_at = datetime(2026, 11, 13, 15, 0, tzinfo=UTC)

    result = brief_by(seriousness, (), filed_at)

    assert result.seriousness == seriousness
    assert result.minutes == minutes
    assert result.due_at == filed_at + timedelta(minutes=minutes)


@pytest.mark.parametrize("seriousness", ["high", "medium", "low"])
def test_any_broken_limit_counts_as_high(seriousness):
    filed_at = datetime(2026, 11, 13, 15, 0, tzinfo=UTC)

    result = brief_by(seriousness, ("wind_knots",), filed_at)

    assert result.seriousness == "high"
    assert result.minutes == 5
    assert result.due_at == filed_at + timedelta(minutes=5)


def test_several_broken_limits_still_count_as_high():
    filed_at = datetime(2026, 6, 1, 8, 30, tzinfo=UTC)

    result = brief_by("low", ["wind_knots", "temp_c", "fuel_pct"], filed_at)

    assert result.seriousness == "high"
    assert result.minutes == 5
    assert result.due_at == datetime(2026, 6, 1, 8, 35, tzinfo=UTC)


def test_a_limit_name_string_is_not_a_sequence_of_limits():
    filed_at = datetime(2026, 11, 13, tzinfo=UTC)

    with pytest.raises(TypeError):
        brief_by("low", "wind_knots", filed_at)


def test_unknown_seriousness_is_rejected_when_limits_hold():
    filed_at = datetime(2026, 11, 13, tzinfo=UTC)

    with pytest.raises(ValueError):
        brief_by("severe", (), filed_at)
