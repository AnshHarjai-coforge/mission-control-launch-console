"""Cost of a report, computed in code from token counts and configured rates.

The model is not asked what a report cost. A code step has 0 tokens. A missing
token count costs 0. Dollars are stored to 6 decimal places and shown to 4.
"""

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

SAMPLE_INPUT_USD_PER_MILLION = Decimal(3)
SAMPLE_OUTPUT_USD_PER_MILLION = Decimal(15)

_SIX_PLACES = Decimal("0.000001")
_FOUR_PLACES = Decimal("0.0001")
_MILLION = Decimal(1_000_000)


def step_cost(
    input_tokens: int | None,
    output_tokens: int | None,
    *,
    input_usd_per_million: Decimal | int | str,
    output_usd_per_million: Decimal | int | str,
) -> Decimal:
    """Return one step's cost in dollars, to 6 decimal places.

    A missing, negative, or otherwise unusable token count contributes 0.
    """
    raw = (
        Decimal(_token_count(input_tokens)) * _rate(input_usd_per_million)
        + Decimal(_token_count(output_tokens)) * _rate(output_usd_per_million)
    ) / _MILLION
    return raw.quantize(_SIX_PLACES, rounding=ROUND_HALF_UP)


def report_cost(step_costs: Sequence[Decimal]) -> Decimal:
    """Return the sum of the step costs, to 6 decimal places."""
    total = Decimal(0)
    for amount in step_costs:
        total += amount
    return total.quantize(_SIX_PLACES, rounding=ROUND_HALF_UP)


def store_cost(amount: Decimal) -> str:
    """Store dollars to 6 decimal places."""
    return format(amount.quantize(_SIX_PLACES, rounding=ROUND_HALF_UP), "f")


def show_cost(amount: Decimal) -> str:
    """Show dollars to 4 decimal places."""
    return format(amount.quantize(_FOUR_PLACES, rounding=ROUND_HALF_UP), "f")


def configured_rate(raw: str, *, default: Decimal) -> Decimal:
    """Read a rate from configuration.

    A blank, negative, or unusable value uses the supplied default. The sample
    defaults are $3 and $15 per million tokens until real prices are set.
    """
    text = raw.strip()
    if text == "":
        return default
    try:
        value = Decimal(text)
    except InvalidOperation:
        return default
    if not value.is_finite() or value < 0:
        return default
    return value


def _token_count(value: int | None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    if value < 0:
        return 0
    return value


def _rate(value: Decimal | int | str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, str)):
        raise TypeError("A rate must be a decimal number")
    try:
        number = value if isinstance(value, Decimal) else Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("A rate must be a decimal number") from exc
    if not number.is_finite():
        raise ValueError("A rate must be a finite number")
    return number
