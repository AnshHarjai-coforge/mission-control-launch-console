"""Decide go or no_go from the three launch limits.

Wind may be at most 25 knots. Temperature may be at least 4 C. Fuel may be
from 98 to 100 percent, including both ends. Comparisons use Decimal values.
"""

from dataclasses import dataclass
from decimal import Decimal

_MAX_WIND_KNOTS = Decimal(25)
_MIN_TEMP_C = Decimal(4)
_MIN_FUEL_PCT = Decimal(98)
_MAX_FUEL_PCT = Decimal(100)

WIND_KNOTS = "wind_knots"
TEMP_C = "temp_c"
FUEL_PCT = "fuel_pct"


@dataclass(frozen=True)
class LimitCheck:
    verdict: str
    broken_limits: tuple[str, ...]


def check_limits(wind: Decimal, temperature: Decimal, fuel: Decimal) -> LimitCheck:
    """Return go, or no_go plus each reading that is outside its limit.

    Broken limits are listed in the order wind, temperature, fuel.
    """
    wind = _exact(wind)
    temperature = _exact(temperature)
    fuel = _exact(fuel)
    broken: list[str] = []
    if wind > _MAX_WIND_KNOTS:
        broken.append(WIND_KNOTS)
    if temperature < _MIN_TEMP_C:
        broken.append(TEMP_C)
    if fuel < _MIN_FUEL_PCT or fuel > _MAX_FUEL_PCT:
        broken.append(FUEL_PCT)
    verdict = "go" if not broken else "no_go"
    return LimitCheck(verdict=verdict, broken_limits=tuple(broken))


def _exact(value: Decimal) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError("Readings must be Decimal values")
    if not value.is_finite():
        raise ValueError("Readings must be finite")
    return value
