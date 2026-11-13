"""Shared workshop fixtures. No test downloads a language model."""

from __future__ import annotations

from decimal import Decimal

import pytest

from dow_workshop.agent import Workload
from dow_workshop.config import DEFAULT_CEILINGS, GuardPolicy
from dow_workshop.model import DeterministicModel


@pytest.fixture
def model() -> DeterministicModel:
    return DeterministicModel()


@pytest.fixture
def short_workload() -> Workload:
    return Workload(
        name="short",
        requests=1,
        iterations_per_request=3,
        tool_calls_per_iteration=2,
        context_pad_tokens=16,
        max_new_tokens=8,
        task="Check the local note.",
    )


@pytest.fixture
def loose_policy() -> GuardPolicy:
    limits = DEFAULT_CEILINGS.as_limits()
    return GuardPolicy(**limits)  # type: ignore[arg-type]


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


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def counting_model() -> CountingModel:
    return CountingModel()
