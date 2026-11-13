"""The "your own agent" arithmetic. Nothing here runs an agent."""

from __future__ import annotations

from decimal import Decimal

import pytest

from dow_workshop.attack_simulator import HIJACKED_WORKLOAD, NORMAL_WORKLOAD, project_workload
from dow_workshop.config import COST_DISCLAIMER, IllustrativeRates
from dow_workshop.exposure import estimate_exposure, format_exposure, project_loop

CLASSROOM = {
    "first_prompt_tokens": 64,
    "tool_text_tokens_per_step": 320,
    "output_tokens_per_call": 64,
    "tool_calls_per_step": 2,
}


def test_classroom_numbers_match_the_measured_run() -> None:
    for workload in (NORMAL_WORKLOAD, HIJACKED_WORKLOAD):
        expected = project_workload(workload)
        loop = project_loop(workload.iterations_per_request, **CLASSROOM)
        assert loop.total_tokens == expected.total_tokens
        assert loop.tool_calls == expected.tool_calls
        assert loop.cost_micro_usd == expected.cost_micro_usd
    assert project_loop(10, **CLASSROOM).total_tokens == 18_560
    assert project_loop(10, **CLASSROOM).largest_prompt == 3_520


def test_exposure_compares_normal_hijacked_and_capped() -> None:
    exposure = estimate_exposure(iteration_limit=10, requests_per_day=1_000, **CLASSROOM)
    assert exposure.normal.total_tokens == 128
    assert exposure.hijacked.total_tokens == 18_560
    assert round(exposure.token_multiplier) == 145
    assert exposure.hijacked_day_micro_usd == 163_360 * 1_000
    # A budget of three normal runs stops the loop before its second step.
    assert exposure.capped.model_calls == 1
    assert exposure.capped.total_tokens <= 3 * exposure.normal.total_tokens
    text = format_exposure(exposure)
    assert "145×" in text
    assert "163.36" in text
    assert COST_DISCLAIMER in text
    assert "nothing ran" in text


def test_a_looser_budget_lets_more_steps_through() -> None:
    tight = estimate_exposure(iteration_limit=10, requests_per_day=1, budget_multiple=3, **CLASSROOM)
    loose = estimate_exposure(iteration_limit=10, requests_per_day=1, budget_multiple=50, **CLASSROOM)
    assert loose.capped.model_calls > tight.capped.model_calls
    assert loose.capped.total_tokens <= 50 * loose.normal.total_tokens
    assert loose.capped.total_tokens < loose.hijacked.total_tokens


def test_the_context_window_stops_the_prompt_growing() -> None:
    free = project_loop(100, **CLASSROOM)
    boxed = project_loop(100, context_window_tokens=2_000, **CLASSROOM)
    assert boxed.largest_prompt == 2_000
    assert boxed.total_tokens < free.total_tokens
    # Past the window every further call costs one full window: growth turns linear.
    longer = project_loop(101, context_window_tokens=2_000, **CLASSROOM)
    assert longer.input_tokens - boxed.input_tokens == 2_000


def test_your_own_prices_are_used() -> None:
    rates = IllustrativeRates(Decimal("1"), Decimal("2"), Decimal("0"))
    exposure = estimate_exposure(iteration_limit=10, requests_per_day=1, rates=rates, **CLASSROOM)
    assert exposure.hijacked.cost_micro_usd == 17_920 * 1 + 640 * 2
    assert "1 USD per million input tokens" in format_exposure(exposure, rates)
    typed = IllustrativeRates(3.0, 15.0, 0.005)
    assert "Rates used: 3 USD per million input tokens, 15 per million" in format_exposure(exposure, typed)


@pytest.mark.parametrize(
    "bad",
    [
        {"iteration_limit": 0},
        {"iteration_limit": 1_000_000},
        {"iteration_limit": 2.5},
        {"iteration_limit": True},
        {"normal_steps": 11},
        {"requests_per_day": 0},
        {"budget_multiple": 0},
        {"first_prompt_tokens": 0},
        {"tool_text_tokens_per_step": -1},
        {"context_window_tokens": 0},
    ],
)
def test_bad_numbers_are_rejected_with_a_message(bad) -> None:
    values = {"iteration_limit": 10, "requests_per_day": 10, **CLASSROOM, **bad}
    with pytest.raises(ValueError):
        estimate_exposure(**values)
