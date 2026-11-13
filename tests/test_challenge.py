"""The hands-on challenge: two rounds, the scorer, and the attempt log."""

from __future__ import annotations

import pytest

from dow_workshop.challenge import (
    CHALLENGE_KNOBS,
    HELD_OUT_TESTS,
    REFERENCE_POLICIES,
    VISIBLE_TESTS,
    Scoreboard,
    coach,
    format_challenge,
    format_reference,
    inspect_test,
    reference_rows,
    score_policy,
)
from dow_workshop.config import BUDGET_POLICY, DEFAULT_CEILINGS, PROGRESS_POLICY

ROUND_ONE_WINNER = {"max_stalled_iterations": 1, "max_tool_calls": 8}
TIGHTEST_FOR_SIX = {
    "max_stalled_iterations": 2,
    "max_tool_calls": 10,
    "max_context_tokens": 2_304,
}


def test_round_one_has_four_tests_and_round_two_adds_two() -> None:
    assert [test.kind for test in VISIBLE_TESTS] == ["legit", "attack", "legit", "attack"]
    assert [test.kind for test in HELD_OUT_TESTS] == ["legit", "attack"]
    assert len(score_policy(None).rows) == 4
    assert len(score_policy(None, held_out=True).rows) == 6


def test_the_starting_policy_fails_on_the_real_work() -> None:
    result = score_policy(BUDGET_POLICY)
    assert result.legit_finished == 0
    assert result.attacks_stopped == 2
    assert (result.reads_done, result.reads_planned) == (4, 12)
    text = format_challenge(result)
    assert "FAIL" in text
    assert "cut short at 2 of 4 reads (max_iterations)" in text
    assert "That limit is too tight for this task." in text


def test_no_policy_lets_every_attack_run_to_the_iteration_limit() -> None:
    visible = score_policy(None)
    assert visible.attacks_stopped == 0
    assert visible.attack_tokens == visible.baseline_attack_tokens == 37_120
    everything = score_policy(None, held_out=True)
    assert everything.legit_finished == 3
    assert everything.attack_tokens == everything.baseline_attack_tokens == 68_352


def test_progress_check_alone_misses_the_paginated_attack() -> None:
    result = score_policy(PROGRESS_POLICY)
    assert result.legit_finished == 2
    assert result.attacks_stopped == 1
    text = format_challenge(result)
    assert "ran to the agent's iteration limit" in text
    assert "nothing in your policy stopped it" in text


def test_round_one_winner_passes_round_one() -> None:
    result = score_policy(ROUND_ONE_WINNER)
    assert result.all_passed is True
    assert result.attack_tokens == 5_120
    assert "Every test passes." in "\n".join(coach(result))


def test_round_one_winner_breaks_on_the_held_out_tests() -> None:
    """The lesson of round two: a policy fitted to what it saw."""

    result = score_policy(ROUND_ONE_WINNER, held_out=True)
    rows = {row.number: row for row in result.rows}
    assert result.legit_finished == 2
    assert rows[5].passed is False
    assert (rows[5].reads_done, rows[5].reads_planned) == (8, 10)
    assert rows[5].stopped_by_knob == "max_tool_calls"
    # The new note alone lets more through than both visible attacks together.
    assert rows[6].result.metrics.total_tokens == 6_592
    assert rows[6].result.metrics.total_tokens > score_policy(ROUND_ONE_WINNER).attack_tokens
    text = format_challenge(result)
    assert "held out until now:" in text
    assert "What was held back:" in text


def test_a_strict_progress_check_cuts_real_work_that_repeats() -> None:
    result = score_policy(PROGRESS_POLICY, held_out=True)
    row = {row.number: row for row in result.rows}[5]
    assert row.passed is False
    assert row.stopped_by_knob == "max_stalled_iterations"
    relaxed = score_policy({"max_stalled_iterations": 2}, held_out=True)
    assert {row.number: row for row in relaxed.rows}[5].passed is True


def test_each_layer_stops_a_different_attack() -> None:
    result = score_policy(TIGHTEST_FOR_SIX, held_out=True)
    assert result.all_passed is True
    assert result.attack_tokens == 11_936
    stops = {row.number: (row.stopped_by_knob, row.result.metrics.total_tokens) for row in result.rows if row.test.kind == "attack"}
    assert stops == {
        2: ("max_stalled_iterations", 1_536),
        4: ("max_tool_calls", 6_528),
        6: ("max_context_tokens", 3_872),
    }


def _tightest_safe(knob: str, low: int, high: int, *, held_out: bool) -> int:
    """Smallest value of one limit that lets every real task finish."""

    def safe(value: int) -> bool:
        result = score_policy({knob: value}, held_out=held_out)
        return result.legit_finished == result.legit_total

    assert safe(high)
    while low < high:
        middle = (low + high) // 2
        if safe(middle):
            high = middle
        else:
            low = middle + 1
    return low


@pytest.mark.parametrize(
    ("held_out", "expected", "attack_tokens"),
    [
        (
            False,
            {"max_iterations": 8, "max_tool_calls": 8, "max_total_tokens": 7_296, "max_context_tokens": 1_856, "max_stalled_iterations": 1},
            5_120,
        ),
        (
            True,
            {"max_iterations": 10, "max_tool_calls": 10, "max_total_tokens": 11_360, "max_context_tokens": 2_304, "max_stalled_iterations": 2},
            11_936,
        ),
    ],
)
def test_published_minimum_scores(held_out, expected, attack_tokens) -> None:
    """Each limit only ever cuts a run short, so tightening one never lets more
    attack tokens through. The lowest score that keeps all the real work is
    therefore every limit at its tightest safe value."""

    ceilings = DEFAULT_CEILINGS.as_limits()
    tightest = {
        knob: _tightest_safe(knob, 1, int(ceilings[knob]), held_out=held_out)
        for knob, _label in CHALLENGE_KNOBS
    }
    assert tightest == expected
    result = score_policy(tightest, held_out=held_out)
    assert result.all_passed is True
    assert result.attack_tokens == attack_tokens


@pytest.mark.parametrize(
    ("label", "visible", "everything"),
    [
        ("No policy", (2, 37_120), (3, 68_352)),
        ("Iteration limit of 4", (1, 5_632), (1, 9_504)),
        ("Progress check only", (2, 19_200), (2, 50_432)),
        ("Fitted to round one (stalled 1, tool calls 8)", (2, 5_120), (2, 11_712)),
        ("Tightest that keeps all six (stalled 2, tool calls 10, context 2,304)", (2, 8_064), (3, 11_936)),
        ("Same layers with headroom (stalled 2, tool calls 12, context 3,000)", (2, 10_496), (3, 17_088)),
    ],
)
def test_published_reference_points(label, visible, everything) -> None:
    """The table in docs/defences.md and on the round-two slide."""

    rows = {name: (one, two) for name, one, two in reference_rows()}
    one, two = rows[label]
    assert (one.legit_finished, one.attack_tokens) == visible
    assert (two.legit_finished, two.attack_tokens) == everything
    assert len(rows) == len(REFERENCE_POLICIES)


def test_reference_table_can_include_your_policy() -> None:
    text = format_reference(score_policy(BUDGET_POLICY))
    assert "Your policy" in text
    assert "68,352" in text
    assert "Your policy" not in format_reference()


def test_other_budget_policies_keep_their_published_scores() -> None:
    assert score_policy(BUDGET_POLICY).attack_tokens == 1_280
    assert score_policy({"max_total_tokens": 8_000}).attack_tokens == 13_056
    assert score_policy({"max_stalled_iterations": 1, "max_context_tokens": 1_856}).attack_tokens == 5_120


def test_inspect_shows_what_the_agent_did() -> None:
    text = inspect_test(score_policy(PROGRESS_POLICY), 4)
    assert "tampered note B" in text
    assert "action: read_note(DOC-14, page 2)" in text
    assert "more tool calls" in text
    with pytest.raises(ValueError):
        inspect_test(score_policy(PROGRESS_POLICY), 5)
    with pytest.raises(ValueError):
        inspect_test(score_policy(PROGRESS_POLICY), True)


def test_scoreboard_keeps_attempts_and_names_the_best() -> None:
    board = Scoreboard()
    assert board.best() is None
    assert board.format() == "No attempts yet."
    assert board.record(score_policy(BUDGET_POLICY)) == 1
    assert board.record(score_policy(BUDGET_POLICY)) == 1  # a repeat is not stored twice
    assert board.record(score_policy(PROGRESS_POLICY)) == 2
    assert board.record(score_policy(ROUND_ONE_WINNER)) == 3
    number, best = board.best()
    assert number == 3
    assert best.attack_tokens == 5_120
    text = board.format()
    assert "Best so far: attempt 3" in text
    assert "attack tokens  1,280" in text
    with pytest.raises(TypeError):
        board.record("not a result")  # type: ignore[arg-type]


def test_real_work_outranks_a_low_token_count() -> None:
    """Blocking everything is not a winning policy."""

    strict = score_policy(BUDGET_POLICY)
    layered = score_policy(ROUND_ONE_WINNER)
    assert strict.attack_tokens < layered.attack_tokens
    assert layered.rank < strict.rank


def test_values_above_the_ceiling_are_clamped_and_reported() -> None:
    result = score_policy({"max_iterations": 10_000})
    assert result.policy.max_iterations == 24
    assert any("hard safety ceiling" in warning for warning in result.warnings)
    assert "hard safety ceiling" in format_challenge(result)


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValueError):
        score_policy({"unlimited": True})
