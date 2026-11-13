from decimal import Decimal

from app.cost import (
    SAMPLE_INPUT_USD_PER_MILLION,
    SAMPLE_OUTPUT_USD_PER_MILLION,
    configured_rate,
    report_cost,
    show_cost,
    step_cost,
    store_cost,
)
from app.trace import RecordedStep, code_step, price_steps


def test_known_tokens_and_rates_set_the_step_cost_and_the_total():
    # 2,000,000 input at $4 per million is $8. 500,000 output at $2 per million is $1.
    first = step_cost(
        2_000_000,
        500_000,
        input_usd_per_million=Decimal(4),
        output_usd_per_million=Decimal(2),
    )
    code = step_cost(
        0,
        0,
        input_usd_per_million=Decimal(4),
        output_usd_per_million=Decimal(2),
    )

    assert first == Decimal("9.000000")
    assert code == Decimal("0.000000")
    assert report_cost([first, code, first]) == Decimal("18.000000")


def test_the_cost_function_uses_the_rates_it_is_given(monkeypatch):
    monkeypatch.setenv("INPUT_USD_PER_MILLION", "99")
    monkeypatch.setenv("OUTPUT_USD_PER_MILLION", "99")

    cost = step_cost(
        1_000_000,
        1_000_000,
        input_usd_per_million=Decimal(2),
        output_usd_per_million=Decimal(5),
    )

    assert cost == Decimal("7.000000")
    assert SAMPLE_INPUT_USD_PER_MILLION == Decimal(3)
    assert SAMPLE_OUTPUT_USD_PER_MILLION == Decimal(15)


def test_a_missing_token_count_costs_zero_and_does_not_crash():
    rates = {
        "input_usd_per_million": Decimal(3),
        "output_usd_per_million": Decimal(15),
    }
    missing = step_cost(None, None, **rates)
    missing_input = step_cost(None, 2_000_000, **rates)
    missing_output = step_cost(2_000_000, None, **rates)
    negative = step_cost(-5, -8, **rates)
    priced, total = price_steps(
        [
            code_step("Report saved", detail="Saved."),
            RecordedStep(
                name="Vehicle part and seriousness",
                kind="model",
                round_number=None,
                input_tokens=None,
                output_tokens=None,
                outcome="error",
                detail="The model could not be reached.",
            ),
        ],
        **rates,
    )

    assert missing == Decimal("0.000000")
    assert missing_input == Decimal("30.000000")
    assert missing_output == Decimal("6.000000")
    assert negative == Decimal("0.000000")
    assert priced[0].cost == Decimal("0.000000")
    assert priced[0].order == 1
    assert priced[1].cost == Decimal("0.000000")
    assert priced[1].order == 2
    assert total == Decimal("0.000000")


def test_dollars_are_stored_to_six_places_and_shown_to_four():
    assert store_cost(Decimal("4.5")) == "4.500000"
    assert store_cost(step_cost(1, 0, input_usd_per_million=Decimal(3), output_usd_per_million=0)) == (
        "0.000003"
    )
    assert show_cost(Decimal(0)) == "0.0000"
    assert show_cost(Decimal("4.5")) == "4.5000"
    assert show_cost(Decimal("0.001050")) == "0.0011"
    assert show_cost(Decimal("0.001040")) == "0.0010"
    assert show_cost(Decimal("0.000015")) == "0.0000"


def test_a_blank_or_unusable_configured_rate_uses_the_default():
    default = Decimal(3)

    assert configured_rate("", default=default) == default
    assert configured_rate("   ", default=default) == default
    assert configured_rate("nope", default=default) == default
    assert configured_rate("-1", default=default) == default
    assert configured_rate("NaN", default=default) == default
    assert configured_rate("2.5", default=default) == Decimal("2.5")
