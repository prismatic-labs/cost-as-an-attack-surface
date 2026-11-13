"""The notebook charts draw from real results and need nothing but matplotlib."""

from __future__ import annotations

import pytest

from dow_workshop.attack_simulator import NORMAL_WORKLOAD, compare_scenarios, run_session
from dow_workshop.challenge import score_policy
from dow_workshop.charts import draw_challenge, draw_comparison, draw_staircase, have_matplotlib
from dow_workshop.config import BUDGET_POLICY

plt = pytest.importorskip("matplotlib.pyplot")


@pytest.fixture(autouse=True)
def _headless(monkeypatch):
    monkeypatch.setenv("MPLBACKEND", "Agg")
    plt.switch_backend("Agg")
    yield
    plt.close("all")


def _texts(figure) -> str:
    return "\n".join(text.get_text() for text in figure.findobj(match=lambda item: hasattr(item, "get_text")))


def test_matplotlib_is_detected() -> None:
    assert have_matplotlib() is True


def test_staircase_has_one_bar_per_model_call() -> None:
    poisoned = run_session(NORMAL_WORKLOAD, notes="poisoned")
    figure = draw_staircase(poisoned)
    bars = figure.axes[0].patches
    assert [round(bar.get_height()) for bar in bars] == list(poisoned.prompt_sizes)
    text = _texts(figure)
    assert "17,920 input tokens" in text
    assert "3,520" in text


def test_comparison_has_the_six_rows() -> None:
    figure = draw_comparison(compare_scenarios())
    assert len(figure.axes[0].patches) == 6
    assert "18,560  ran to the iteration limit" in _texts(figure)


@pytest.mark.parametrize("held_out", [False, True])
def test_challenge_chart_states_the_score(held_out: bool) -> None:
    result = score_policy(BUDGET_POLICY, held_out=held_out)
    figure = draw_challenge(result)
    text = _texts(figure)
    assert f"Real work finished: 0 of {result.legit_total} tasks" in text
    assert f"{result.attack_tokens:,} of {result.baseline_attack_tokens:,}" in text
    assert "cut short at 2 of 4 (max_iterations)" in text
