from decimal import Decimal

import pytest

from app.limits import check_limits


@pytest.mark.parametrize(
    ("wind", "temperature", "fuel", "verdict", "broken"),
    [
        ("25", "20", "99", "go", ()),
        ("25.1", "20", "99", "no_go", ("wind_knots",)),
        ("10", "4", "99", "go", ()),
        ("10", "3.9", "99", "no_go", ("temp_c",)),
        ("10", "20", "98", "go", ()),
        ("10", "20", "97.9", "no_go", ("fuel_pct",)),
        ("10", "20", "100", "go", ()),
        ("10", "20", "100.1", "no_go", ("fuel_pct",)),
        ("25", "4", "98", "go", ()),
        ("25", "4", "100", "go", ()),
        ("25.1", "4", "98", "no_go", ("wind_knots",)),
        ("25", "3.9", "100", "no_go", ("temp_c",)),
        ("25", "4", "97.9", "no_go", ("fuel_pct",)),
        ("25", "4", "100.1", "no_go", ("fuel_pct",)),
        ("25.1", "3.9", "97.9", "no_go", ("wind_knots", "temp_c", "fuel_pct")),
        ("25.1", "3.9", "100.1", "no_go", ("wind_knots", "temp_c", "fuel_pct")),
    ],
)
def test_limit_boundaries(wind, temperature, fuel, verdict, broken):
    result = check_limits(Decimal(wind), Decimal(temperature), Decimal(fuel))

    assert result.verdict == verdict
    assert result.broken_limits == broken


def test_trailing_zeros_stay_on_the_line():
    low_fuel = check_limits(Decimal("25.0"), Decimal("4.00"), Decimal("98.000"))
    high_fuel = check_limits(Decimal(25), Decimal(4), Decimal("100.00"))

    assert low_fuel.verdict == "go"
    assert low_fuel.broken_limits == ()
    assert high_fuel.verdict == "go"
    assert high_fuel.broken_limits == ()


def test_float_readings_are_rejected():
    with pytest.raises(TypeError):
        check_limits(25.1, Decimal(4), Decimal(98))


def test_non_finite_readings_are_rejected():
    with pytest.raises(ValueError):
        check_limits(Decimal("NaN"), Decimal(4), Decimal(98))
    with pytest.raises(ValueError):
        check_limits(Decimal(25), Decimal("Infinity"), Decimal(98))
