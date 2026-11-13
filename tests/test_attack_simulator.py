"""The six workshop rows, amplification arithmetic, and the hard safety ceiling."""

from __future__ import annotations

from decimal import Decimal

from dow_workshop.agent import Workload
from dow_workshop.attack_simulator import (
    HIJACKED_WORKLOAD,
    NORMAL_WORKLOAD,
    amplification_note,
    clamp_workload,
    compare_scenarios,
    format_growth_table,
    growth_table,
    iteration_input_sizes,
    project_workload,
    run_session,
)
from dow_workshop.config import DEFAULT_CEILINGS, GuardPolicy, sandbox_policy
from dow_workshop.metrics import format_usd_micro
from dow_workshop.mock_tools import NOTE_SETS


def test_six_rows_tell_the_story() -> None:
    normal, poisoned, budget, long_budget, progress, long_progress = compare_scenarios()

    assert [r.metrics.requests_started for r in (normal, poisoned, budget, progress)] == [1, 1, 1, 1]
    assert normal.metrics.total_tokens == 128
    assert poisoned.metrics.total_tokens == 18_560
    assert poisoned.metrics.model_calls == 10
    assert poisoned.metrics.tool_calls == 20
    assert poisoned.metrics.stopped_by == "iteration limit"
    assert poisoned.metrics.limit_kind is None

    assert budget.metrics.limit_kind == "iterations"
    assert budget.metrics.total_tokens == 640
    assert budget.metrics.prevented_total_tokens == 18_560 - 640
    assert budget.metrics.prevented_iterations == 8

    # The budget also cuts a legitimate task short: the false positive.
    assert long_budget.metrics.limit_kind == "iterations"
    assert long_budget.metrics.answer_status == "partial"

    # The progress check stops the loop and lets the legitimate task finish.
    assert progress.metrics.limit_kind == "no_progress"
    assert progress.metrics.total_tokens == 640
    assert long_progress.metrics.answer_status == "complete"
    assert long_progress.metrics.total_tokens == 1_856

    note = amplification_note(normal, poisoned)
    assert "1 → 1" in note
    assert "×145" in note
    assert "never sent a request" in note


def test_staircase_is_measured_and_matches_the_arithmetic() -> None:
    poisoned = compare_scenarios()[1]
    expected = (64, 448, 832, 1216, 1600, 1984, 2368, 2752, 3136, 3520)
    assert poisoned.prompt_sizes == expected
    assert iteration_input_sizes(HIJACKED_WORKLOAD) == expected
    projection = project_workload(HIJACKED_WORKLOAD)
    assert projection.total_tokens == poisoned.metrics.total_tokens
    assert projection.tool_calls == poisoned.metrics.tool_calls


def test_tokens_grow_with_the_square_of_the_steps() -> None:
    rows = growth_table()
    assert [row.iterations for row in rows] == [10, 20, 40, 80]
    assert [row.total_tokens for row in rows] == [18_560, 75_520, 304_640, 1_223_680]
    for shorter, longer in zip(rows, rows[1:]):
        assert 3.9 < longer.total_tokens / shorter.total_tokens < 4.1
    table = format_growth_table(rows)
    assert "nothing runs" in table
    assert "45,324.80" in table


def test_projection_matches_an_unconstrained_sandbox_run() -> None:
    projection = project_workload(NORMAL_WORKLOAD)
    result = run_session(NORMAL_WORKLOAD, policy=sandbox_policy())
    assert result.metrics.input_tokens == projection.input_tokens
    assert result.metrics.output_tokens == projection.output_tokens
    assert result.metrics.tool_calls == projection.tool_calls


def test_runs_can_be_repeated() -> None:
    first = run_session(NORMAL_WORKLOAD, notes="poisoned")
    second = run_session(NORMAL_WORKLOAD, notes="poisoned")
    assert first.metrics.total_tokens == second.metrics.total_tokens


def test_user_schedule_cannot_bypass_hard_ceilings() -> None:
    requested = Workload(
        name="oversized",
        requests=6,
        iterations_per_request=10_000,
        tool_calls_per_iteration=10_000,
        context_pad_tokens=10_000,
        max_new_tokens=10_000,
    )
    loose = GuardPolicy(
        max_iterations=100_000,
        max_requests=100_000,
        max_tool_calls=100_000,
        max_total_tokens=5_000_000,
        max_context_tokens=100_000,
        max_output_tokens_per_step=10_000,
        max_stalled_iterations=100_000,
        max_execution_seconds=3_000,
        max_estimated_cost_usd=Decimal("100"),
    )
    for notes in NOTE_SETS:
        result = run_session(requested, notes=notes, policy=loose, max_steps=1_000)
        assert result.schedule.requests <= DEFAULT_CEILINGS.max_requests
        assert result.metrics.iterations <= DEFAULT_CEILINGS.max_iterations
        assert result.metrics.tool_calls <= DEFAULT_CEILINGS.max_tool_calls
        assert result.metrics.total_tokens <= DEFAULT_CEILINGS.max_total_tokens
        assert result.metrics.max_context_tokens <= DEFAULT_CEILINGS.max_context_tokens
        assert result.schedule.max_new_tokens <= DEFAULT_CEILINGS.max_output_tokens_per_step
        assert result.schedule.context_pad_tokens <= DEFAULT_CEILINGS.max_context_pad_tokens
        assert any("hard safety ceiling" in warning for warning in result.metrics.warnings)


def test_clamp_reduces_the_product_of_requests_and_iterations() -> None:
    requested = Workload(
        name="wide",
        requests=6,
        iterations_per_request=24,
        tool_calls_per_iteration=1,
        context_pad_tokens=8,
        max_new_tokens=8,
    )
    schedule, warnings = clamp_workload(requested)
    assert schedule.requests * schedule.iterations_per_request <= DEFAULT_CEILINGS.max_iterations
    assert warnings


def test_simulation_source_does_not_target_networks() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "dow_workshop"
    banned = (
        "openai",
        "anthropic",
        "api.openai.com",
        "import socket",
        "socket.",
        "urllib",
        "http.client",
        "httpx",
        "requests.",
        "huggingface",
        "from_pretrained",
    )
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        for token in banned:
            assert token not in text, f"{path.name} contains {token}"


def test_illustrative_cost_is_exact() -> None:
    normal, poisoned = compare_scenarios()[:2]
    assert normal.metrics.illustrative_cost_micro_usd == 11_152
    assert format_usd_micro(poisoned.metrics.illustrative_cost_micro_usd) == "0.163360"
    assert normal.metrics.cost_disclaimer.startswith("ILLUSTRATIVE SIMULATED COST")
