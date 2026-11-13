"""Runtime guard limits, circuit breaker, and pre-work checks."""

from __future__ import annotations

from decimal import Decimal

import pytest

from dow_workshop.agent import Agent, Workload
from dow_workshop.config import DEFAULT_CEILINGS, GuardPolicy, policy_from_mapping
from dow_workshop.model import DeterministicModel
from dow_workshop.runtime_guard import (
    CircuitOpenError,
    LimitKind,
    ReentryError,
    RuntimeGuard,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class CountingModel(DeterministicModel):
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, prompt: str, max_new_tokens: int):
        self.calls += 1
        return super().generate(prompt, max_new_tokens)


def _workload(**overrides: int | str) -> Workload:
    values: dict[str, int | str] = {
        "name": "guarded",
        "requests": 1,
        "iterations_per_request": 3,
        "tool_calls_per_iteration": 2,
        "context_pad_tokens": 8,
        "max_new_tokens": 8,
    }
    values.update(overrides)
    return Workload(**values)  # type: ignore[arg-type]


def test_iteration_limit_trips_before_the_next_model_call() -> None:
    model = CountingModel()
    guard = RuntimeGuard(policy=GuardPolicy(max_iterations=1))
    with guard.session():
        Agent(model).run(_workload(), guard)

    assert model.calls == 1
    assert guard.iterations == 1
    assert guard.limit_kind is LimitKind.ITERATIONS
    assert "before the next unit of work" in (guard.stop_reason or "")


def test_token_limit_trips_before_any_generation() -> None:
    model = CountingModel()
    guard = RuntimeGuard(policy=GuardPolicy(max_total_tokens=10))
    with guard.session():
        Agent(model).run(_workload(iterations_per_request=1, tool_calls_per_iteration=0), guard)

    assert model.calls == 0
    assert guard.model_calls == 0
    assert guard.limit_kind is LimitKind.TOKENS


def test_tool_call_limit_trips_before_the_extra_tool() -> None:
    model = CountingModel()
    guard = RuntimeGuard(policy=GuardPolicy(max_tool_calls=1))
    with guard.session():
        Agent(model).run(_workload(iterations_per_request=1, tool_calls_per_iteration=3), guard)

    assert model.calls == 1
    assert guard.tool_calls == 1
    assert guard.limit_kind is LimitKind.TOOL_CALLS


def test_context_limit_trips_before_the_tool_runs() -> None:
    model = CountingModel()
    guard = RuntimeGuard(policy=GuardPolicy(max_context_tokens=100))
    workload = Workload(
        name="context",
        requests=1,
        iterations_per_request=1,
        tool_calls_per_iteration=1,
        context_pad_tokens=48,
        max_new_tokens=32,
    )
    with guard.session():
        Agent(model).run(workload, guard)

    assert model.calls == 1
    assert guard.tool_calls == 0
    assert guard.limit_kind is LimitKind.CONTEXT


def test_context_limit_trips_before_model_when_reply_would_exceed_it() -> None:
    model = CountingModel()
    guard = RuntimeGuard(policy=GuardPolicy(max_context_tokens=80))
    workload = Workload(
        name="context-reply",
        requests=1,
        iterations_per_request=1,
        tool_calls_per_iteration=0,
        context_pad_tokens=8,
        max_new_tokens=32,
    )
    with guard.session():
        Agent(model).run(workload, guard)

    assert model.calls == 0
    assert guard.max_context_tokens <= 80
    assert guard.limit_kind is LimitKind.CONTEXT


def test_time_limit_uses_the_injected_clock() -> None:
    clock = FakeClock()
    model = CountingModel()

    class SlowModel(CountingModel):
        def generate(self, prompt: str, max_new_tokens: int):
            clock.advance(10)
            return super().generate(prompt, max_new_tokens)

    guard = RuntimeGuard(policy=GuardPolicy(max_execution_seconds=5), clock=clock)
    with guard.session():
        Agent(SlowModel()).run(
            _workload(iterations_per_request=3, tool_calls_per_iteration=0),
            guard,
        )

    assert guard.limit_kind is LimitKind.TIME
    assert guard.model_calls == 1
    assert guard.elapsed_seconds() >= 5


def test_cost_limit_trips_before_generation() -> None:
    model = CountingModel()
    guard = RuntimeGuard(policy=GuardPolicy(max_estimated_cost_usd=Decimal("0.0001")))
    with guard.session():
        Agent(model).run(_workload(iterations_per_request=1, tool_calls_per_iteration=0), guard)

    assert model.calls == 0
    assert guard.limit_kind is LimitKind.COST
    assert "ILLUSTRATIVE SIMULATED COST" in (guard.stop_reason or "")


def test_cost_limit_can_stop_on_the_tool_before_it_runs() -> None:
    model = CountingModel()
    # The first model call (64 input and 8 output tokens, 312 micro-USD) stays
    # under this budget. The mock tool fee pushes the next check over it.
    guard = RuntimeGuard(policy=GuardPolicy(max_estimated_cost_usd=Decimal("0.001")))
    with guard.session():
        Agent(model).run(
            _workload(iterations_per_request=1, tool_calls_per_iteration=1, max_new_tokens=8),
            guard,
        )

    assert model.calls == 1
    assert guard.tool_calls == 0
    assert guard.limit_kind is LimitKind.COST


def test_circuit_breaker_stays_open_until_reset() -> None:
    guard = RuntimeGuard(policy=GuardPolicy(max_iterations=1))
    with guard.session():
        Agent(DeterministicModel()).run(_workload(), guard)
    assert guard.tripped is True
    with pytest.raises(CircuitOpenError):
        with guard.session():
            pass
    guard.reset()
    assert guard.tripped is False
    with guard.session():
        guard.before_request()
    assert guard.requests_started == 1


def test_reentry_is_refused_without_opening_a_second_session() -> None:
    guard = RuntimeGuard()
    with guard.session():
        with pytest.raises(ReentryError):
            with guard.session():
                pass
        guard.before_request()
    assert guard.tripped is False
    assert guard.requests_started == 1


def test_checks_outside_a_session_are_rejected() -> None:
    guard = RuntimeGuard()
    with pytest.raises(RuntimeError):
        guard.before_iteration()


def test_requested_policy_above_the_ceiling_is_clamped() -> None:
    guard = RuntimeGuard(
        policy=GuardPolicy(
            max_iterations=50_000,
            max_tool_calls=50_000,
            max_total_tokens=2_000_000,
            max_requests=50_000,
            max_context_tokens=50_000,
            max_output_tokens_per_step=5_000,
            max_execution_seconds=3_000,
            max_estimated_cost_usd=Decimal("80"),
        )
    )
    assert guard.policy.max_iterations == DEFAULT_CEILINGS.max_iterations
    assert guard.policy.max_tool_calls == DEFAULT_CEILINGS.max_tool_calls
    assert guard.policy.max_total_tokens == DEFAULT_CEILINGS.max_total_tokens
    assert guard.policy.max_estimated_cost_usd == DEFAULT_CEILINGS.max_estimated_cost_usd
    assert guard.clamp_warnings


def test_unknown_policy_field_is_rejected() -> None:
    with pytest.raises(ValueError):
        policy_from_mapping({"max_iterations": 2, "unlimited": True})


def test_zero_iteration_budget_blocks_the_model() -> None:
    model = CountingModel()
    guard = RuntimeGuard(policy=GuardPolicy(max_iterations=0))
    with guard.session():
        Agent(model).run(_workload(iterations_per_request=1, tool_calls_per_iteration=0), guard)
    assert model.calls == 0
    assert guard.limit_kind is LimitKind.ITERATIONS


def _stalled_workload(iterations: int = 4) -> Workload:
    # Generic plans search and re-read DOC-14, so the second iteration repeats the first.
    return _workload(iterations_per_request=iterations, tool_calls_per_iteration=2)


def test_progress_check_refuses_the_iteration_after_a_repeat() -> None:
    model = CountingModel()
    guard = RuntimeGuard(policy=GuardPolicy(max_stalled_iterations=1))
    with guard.session():
        Agent(model).run(_stalled_workload(), guard)

    assert model.calls == 2
    assert guard.stalled_iterations == 1
    assert guard.limit_kind is LimitKind.NO_PROGRESS
    assert "repeats" in (guard.stop_reason or "")


def test_progress_check_allows_new_results() -> None:
    model = CountingModel()
    guard = RuntimeGuard(policy=GuardPolicy(max_stalled_iterations=1))
    workload = Workload(
        name="compare",
        requests=1,
        iterations_per_request=4,
        tool_calls_per_iteration=1,
        context_pad_tokens=16,
        max_new_tokens=8,
        notes=("DOC-11", "DOC-12", "DOC-13", "DOC-14"),
    )
    with guard.session():
        Agent(model).run(workload, guard)

    assert model.calls == 4
    assert guard.stalled_iterations == 0
    assert guard.tripped is False


def test_iterations_without_tools_do_not_count_as_stalled() -> None:
    guard = RuntimeGuard(policy=GuardPolicy(max_stalled_iterations=1))
    with guard.session():
        Agent(DeterministicModel()).run(
            _workload(iterations_per_request=3, tool_calls_per_iteration=0), guard
        )
    assert guard.tripped is False
    assert guard.stalled_iterations == 0


def test_progress_check_needs_at_least_one_iteration() -> None:
    with pytest.raises(ValueError):
        GuardPolicy(max_stalled_iterations=0)


def test_guard_keeps_hashes_not_tool_text() -> None:
    guard = RuntimeGuard()
    with guard.session():
        guard.before_request()
        guard.before_iteration()
        guard.before_tool_call()
        guard.record_tool_call("read_note", "secret operations text")
    assert all("secret" not in item for item in guard._seen_results)
    assert all("secret" not in event for event in guard.events)
