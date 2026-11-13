"""Cost estimation and the split between real and simulated measurements."""

from __future__ import annotations

from decimal import Decimal

import pytest

from dow_workshop.attack_simulator import NORMAL_WORKLOAD, compare_scenarios, run_session
from dow_workshop.config import COST_DISCLAIMER, IllustrativeRates, sandbox_policy
from dow_workshop.metrics import (
    comparison_rows,
    cost_micro_usd,
    estimate_cost,
    estimate_tokens,
    format_comparison,
    format_usd,
    format_usd_micro,
    text_with_token_count,
)


def test_cost_formula_uses_decimal_micro_usd() -> None:
    rates = IllustrativeRates(
        input_usd_per_million_tokens=Decimal("1"),
        output_usd_per_million_tokens=Decimal("4"),
        usd_per_tool_call=Decimal("0.5"),
    )
    breakdown = estimate_cost(1_000_000, 1_000_000, 2, rates)
    assert breakdown.input_micro_usd == 1_000_000
    assert breakdown.output_micro_usd == 4_000_000
    assert breakdown.tool_micro_usd == 1_000_000
    assert breakdown.total_micro_usd == 6_000_000
    assert breakdown.total_display == "6.000000"
    assert breakdown.disclaimer == COST_DISCLAIMER


def test_zero_consumption_has_zero_illustrative_cost() -> None:
    assert cost_micro_usd(0, 0, 0) == 0
    assert format_usd_micro(0) == "0.000000"


def test_readable_usd_rounding() -> None:
    assert format_usd(45_324_800_000) == "45,324.80"
    assert format_usd(163_360, 4) == "0.1634"


def test_negative_rates_and_counts_are_rejected() -> None:
    with pytest.raises(ValueError):
        IllustrativeRates(input_usd_per_million_tokens=Decimal("-1"))
    with pytest.raises(ValueError):
        cost_micro_usd(-1, 0, 0)
    with pytest.raises(TypeError):
        estimate_tokens(None)  # type: ignore[arg-type]


def test_token_fitter_hits_the_requested_count() -> None:
    text = text_with_token_count(64, "Summarise the local operations note.")
    assert estimate_tokens(text) == 64
    assert estimate_tokens("") == 0


def test_grouped_metrics_separate_real_and_simulated_figures() -> None:
    result = run_session(NORMAL_WORKLOAD, policy=sandbox_policy())
    grouped = result.metrics.grouped()
    assert grouped["real_measurements"]["total_tokens"] == 128
    assert "illustrative_cost_usd" not in grouped["real_measurements"]
    simulated = grouped["simulated_measurements"]
    assert simulated["disclaimer"] == COST_DISCLAIMER
    assert simulated["illustrative_cost_usd"] == "0.011152"
    assert grouped["prevention"]["answer_status"] == "complete"
    assert "Google Colab" in grouped["operational_limitations"][0]


def test_comparison_table_labels_the_cost_as_illustrative() -> None:
    results = compare_scenarios()
    rows = comparison_rows([item.metrics for item in results])
    table = format_comparison([item.metrics for item in results])
    assert [row["scenario"] for row in rows] == [
        "Normal request",
        "Poisoned note, no policy",
        "Poisoned note, budget",
        "Long task, budget",
        "Poisoned note, progress check",
        "Long task, progress check",
    ]
    assert COST_DISCLAIMER in table
    assert "0.163360" in table
    assert "18,560" in table
    assert "seconds" not in table
    assert "Lead with tokens" in table
    with_time = format_comparison([item.metrics for item in results], include_duration=True)
    assert "seconds" in with_time
    assert "wall-clock" in with_time
