"""Turn a user prompt into a visible, deterministic agent plan.

A production agent lets the model choose the next tool. This classroom agent
is scripted so every machine prints the same arithmetic. It has one habit that
real agents share: it follows a "keep going" instruction wherever it reads one,
in the user's prompt or inside a tool result. The marker list below is short on
purpose. A real model follows far more phrasings than any filter can list,
which is why the defence in this workshop is a budget, not a phrase filter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from dow_workshop.config import (
    AGENT_MAX_STEPS,
    DEFAULT_NOTE,
    NOTE_TOKENS,
    OUTPUT_TOKENS,
)

if TYPE_CHECKING:
    from dow_workshop.agent import Workload


KEEP_GOING_MARKERS: tuple[str, ...] = (
    "keep searching",
    "keep looking",
    "keep reading",
    "keep checking",
    "until you are sure",
    "until you are certain",
    "do not stop",
    "check everything",
    "checked everything",
    "verify everything",
    "verified everything",
    "be exhaustive",
)

_CONTRACTIONS = (
    ("don't", "do not"),
    ("you're", "you are"),
    ("you've", "you have"),
    ("doesn't", "does not"),
)


def _normalise(text: str) -> str:
    lowered = text.lower().replace("’", "'").replace("‘", "'")
    for short, long in _CONTRACTIONS:
        lowered = lowered.replace(short, long)
    return " ".join(lowered.split())


def asks_to_keep_going(text: str) -> bool:
    """True when the text tells the agent not to stop."""

    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must be a non-empty string.")
    normal = _normalise(text)
    return any(marker in normal for marker in KEEP_GOING_MARKERS)


def notes_in(text: str) -> tuple[str, ...]:
    """Note ids a prompt asks for, in order. ``DOC-11 to DOC-14`` is a range."""

    found = re.search(r"DOC-(\d+)\s*(?:to|through|-)\s*DOC-(\d+)", text, re.IGNORECASE)
    if found:
        start, end = int(found.group(1)), int(found.group(2))
        if start <= end:
            return tuple(f"DOC-{number}" for number in range(start, end + 1))
    seen: list[str] = []
    for match in re.findall(r"DOC-(\d+)", text, re.IGNORECASE):
        note = f"DOC-{match}"
        if note not in seen:
            seen.append(note)
    return tuple(seen)


_REREAD = re.compile(r"\b(?:re-?read|re-?check|double-?check)\b", re.IGNORECASE)


def split_rereads(text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Notes to read first, then notes the prompt asks to read a second time.

    ``Compare DOC-11 to DOC-13, then re-read DOC-12`` gives three notes and one
    re-read. A prompt with no such request gives no re-reads.
    """

    found = _REREAD.search(text)
    if not found:
        return notes_in(text), ()
    return notes_in(text[: found.start()]), notes_in(text[found.end() :])


@dataclass(frozen=True)
class AgentPlan:
    """The prompt, the schedule it causes, and why."""

    prompt: str
    kind: str
    workload: "Workload"
    reason: str


def plan_from_prompt(prompt: str, *, requests: int = 1) -> AgentPlan:
    """Map a user prompt onto a workload.

    - A prompt that says not to stop: search and re-read until the iteration limit.
    - A prompt that names several notes: read one note per model call. If it
      also asks to re-read some of them, those reads follow, one per call.
    - Anything else: one model call, then search and read one note.
    """

    from dow_workshop.agent import Workload

    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt must be a non-empty string.")
    text = prompt.strip()
    notes, rereads = split_rereads(text)
    if asks_to_keep_going(text):
        kind = "keep_going"
        workload = Workload(
            name="keep going",
            requests=requests,
            iterations_per_request=AGENT_MAX_STEPS,
            tool_calls_per_iteration=2,
            context_pad_tokens=NOTE_TOKENS,
            max_new_tokens=OUTPUT_TOKENS,
            task=text,
        )
        reason = (
            "The prompt tells the agent to keep searching until it is sure. "
            "The agent searches and re-reads until its iteration limit."
        )
    elif len(notes) > 1:
        kind = "compare"
        workload = Workload(
            name="compare",
            requests=requests,
            iterations_per_request=len(notes) + len(rereads),
            tool_calls_per_iteration=1,
            context_pad_tokens=NOTE_TOKENS,
            max_new_tokens=OUTPUT_TOKENS,
            task=text,
            notes=notes + rereads,
        )
        reason = (
            f"The prompt names {len(notes)} notes. The agent reads one per model call, "
            "then compares them."
        )
        if rereads:
            reason = (
                f"The prompt names {len(notes)} notes and asks for {len(rereads)} of them "
                "to be read again. The agent reads one per model call, then compares them."
            )
    else:
        kind = "summary"
        workload = Workload(
            name="summary",
            requests=requests,
            iterations_per_request=1,
            tool_calls_per_iteration=2,
            context_pad_tokens=NOTE_TOKENS,
            max_new_tokens=OUTPUT_TOKENS,
            task=text,
            notes=(notes[0],) if notes else (DEFAULT_NOTE,),
        )
        reason = "The prompt asks for one summary. The agent searches, reads one note, and stops."
    return AgentPlan(prompt=text, kind=kind, workload=workload, reason=reason)


def thought_for(
    workload: "Workload",
    iteration_index: int,
    *,
    obeying: bool,
    calls: tuple[str, ...],
) -> str:
    """One ReAct-style thought for the transcript. Not a billed token source."""

    if iteration_index < 0:
        raise ValueError("iteration_index must be non-negative.")
    tools = ", ".join(calls) if calls else "no tools"
    if obeying and iteration_index == 0:
        return f"The user said to keep searching until I am sure. Start with {tools}."
    if obeying:
        return f"I was told to keep going until I am sure. I am not sure yet. Next: {tools}."
    if len(workload.notes) > 1:
        position = iteration_index % len(workload.notes)
        note = workload.notes[position]
        if note in workload.notes[:position]:
            return f"Read {note} a second time to confirm. Next: {tools}."
        return (
            f"Read note {iteration_index + 1} of {len(workload.notes)}. Next: {tools}."
        )
    return f"Find the note and read it. Next: {tools}, then answer."
