"""Prompt-driven plans, the keep-going detector, and the transcript."""

from __future__ import annotations

import pytest

from dow_workshop.attack_simulator import run_from_prompt
from dow_workshop.config import (
    AGENT_MAX_STEPS,
    DEFAULT_TASK,
    KEEP_GOING_TASK,
    LONG_TASK,
    LONGER_TASK,
    RECHECK_TASK,
    sandbox_policy,
)
from dow_workshop.mock_tools import INJECTION_BULKY, INJECTION_PAGED, INJECTION_REPEAT
from dow_workshop.planner import asks_to_keep_going, notes_in, plan_from_prompt, split_rereads


@pytest.mark.parametrize(
    "text",
    [
        "Keep searching until you are sure.",
        "Keep looking until you're certain.",
        "Be exhaustive: check every note before answering.",
        "Don't stop until you've verified everything.",
        "Don’t stop until you’ve checked everything.",
        INJECTION_REPEAT,
        INJECTION_PAGED.format(next_page=2),
        INJECTION_BULKY.format(next_page=2),
    ],
)
def test_keep_going_phrasings_are_detected(text: str) -> None:
    assert asks_to_keep_going(text) is True


@pytest.mark.parametrize("text", [DEFAULT_TASK, LONG_TASK, LONGER_TASK, RECHECK_TASK])
def test_ordinary_tasks_are_not_keep_going(text: str) -> None:
    assert asks_to_keep_going(text) is False


def test_summary_prompt_is_one_call_and_two_tools() -> None:
    plan = plan_from_prompt(DEFAULT_TASK)
    assert plan.kind == "summary"
    assert plan.workload.iterations_per_request == 1
    assert plan.workload.tool_calls_per_iteration == 2
    assert plan.workload.notes == ("DOC-14",)


def test_compare_prompt_reads_one_note_per_call() -> None:
    plan = plan_from_prompt(LONG_TASK)
    assert plan.kind == "compare"
    assert plan.workload.notes == ("DOC-11", "DOC-12", "DOC-13", "DOC-14")
    assert plan.workload.iterations_per_request == 4
    assert plan_from_prompt(LONGER_TASK).workload.iterations_per_request == 8


def test_a_prompt_can_ask_for_notes_to_be_read_again() -> None:
    assert split_rereads("Compare DOC-11 to DOC-13, then re-read DOC-12") == (
        ("DOC-11", "DOC-12", "DOC-13"),
        ("DOC-12",),
    )
    assert split_rereads(LONG_TASK) == (("DOC-11", "DOC-12", "DOC-13", "DOC-14"), ())
    plan = plan_from_prompt(RECHECK_TASK)
    assert plan.kind == "compare"
    assert plan.workload.iterations_per_request == AGENT_MAX_STEPS
    assert plan.workload.notes[-2:] == ("DOC-15", "DOC-16")
    assert "read again" in plan.reason
    result = run_from_prompt(RECHECK_TASK, policy=sandbox_policy())
    assert result.metrics.answer_status == "complete"
    assert result.metrics.total_tokens == 11_360
    assert len(result.reads) == 10
    assert "decision: Read DOC-15 a second time to confirm." in "\n".join(result.transcript)


def test_direct_keep_going_prompt_runs_to_the_iteration_limit() -> None:
    plan = plan_from_prompt(KEEP_GOING_TASK)
    assert plan.kind == "keep_going"
    result = run_from_prompt(KEEP_GOING_TASK, policy=sandbox_policy())
    assert result.metrics.model_calls == AGENT_MAX_STEPS
    assert result.metrics.stopped_by == "iteration limit"
    assert result.metrics.hijacked is False


def test_note_ranges_and_lists() -> None:
    assert notes_in("DOC-11 to DOC-13") == ("DOC-11", "DOC-12", "DOC-13")
    assert notes_in("Read DOC-15 and DOC-12, then DOC-15") == ("DOC-15", "DOC-12")
    assert notes_in("no notes here") == ()


def test_empty_prompt_is_rejected() -> None:
    with pytest.raises(ValueError):
        asks_to_keep_going("  ")
    with pytest.raises(ValueError):
        plan_from_prompt("")


def test_transcript_shows_the_moment_of_hijack() -> None:
    result = run_from_prompt(DEFAULT_TASK, notes="poisoned", policy=sandbox_policy())
    text = "\n".join(result.transcript)
    assert text.startswith(f"user: {DEFAULT_TASK}")
    assert "action: read_note(DOC-14)" in text
    assert "The note also contains an instruction." in text
    assert "decision: The note says to keep searching until I am sure." in text
    assert text.index("contains an instruction") < text.index("I will do what it says")
