"""A small, visible agent loop.

One iteration is one model call followed by mock tool calls. The plan comes
from ``plan_from_prompt``. After every tool result the agent checks whether the
text told it to keep going. If it did, the agent obeys: it searches and re-reads
until it is "sure", which in practice means until its own iteration limit. That habit
is the attack surface. The guard can refuse the next model call or tool call
at any point, and the agent then returns a partial answer instead of nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

from dow_workshop.config import AGENT_MAX_STEPS, DEFAULT_NOTE, DEFAULT_TASK
from dow_workshop.metrics import initial_context_tokens
from dow_workshop.mock_tools import NOTES, MockToolset, ToolCall, ToolResult
from dow_workshop.model import ModelOutput
from dow_workshop.planner import asks_to_keep_going, thought_for
from dow_workshop.runtime_guard import GuardError, RuntimeGuard

__all__ = ["Agent", "AgentRun", "ModelOutput", "Workload"]


@dataclass(frozen=True)
class Workload:
    """Declared plan for one local experiment.

    ``requests`` is how many user messages start the plan.
    ``iterations_per_request`` is how many model calls each message expands into
    if nothing in the notes changes the agent's mind.
    ``tool_calls_per_iteration`` is how many mock tools run after each model call.
    ``context_pad_tokens`` is the size of each tool result.
    ``max_new_tokens`` is the output reserved for each model call.
    ``notes`` lists the notes the plan reads. Several notes means one per model
    call. A note may appear twice when the task asks for it to be re-read.
    """

    name: str
    requests: int
    iterations_per_request: int
    tool_calls_per_iteration: int
    context_pad_tokens: int
    max_new_tokens: int
    task: str = DEFAULT_TASK
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("workload name must be a non-empty string.")
        if not isinstance(self.task, str) or not self.task.strip():
            raise ValueError("task must be a non-empty string.")
        _count(self.requests, "requests", minimum=1)
        _count(self.iterations_per_request, "iterations_per_request", minimum=1)
        _count(self.tool_calls_per_iteration, "tool_calls_per_iteration", minimum=0)
        _count(self.max_new_tokens, "max_new_tokens", minimum=1)
        _count(self.context_pad_tokens, "context_pad_tokens", minimum=1)
        notes = tuple(self.notes)
        for note in notes:
            if note not in NOTES:
                raise ValueError(
                    f"Unknown note {note!r}. The local notes are DOC-11 to DOC-18."
                )
        object.__setattr__(self, "notes", notes)
        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(self, "task", self.task.strip())


def _count(value: object, name: str, *, minimum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer.")
    if value < minimum or value > 1_000_000:
        raise ValueError(f"{name} must be between {minimum} and 1000000.")


@dataclass(frozen=True)
class AgentRun:
    """What the agent returned and why it stopped."""

    answer: str
    answer_status: str
    stopped_by: str
    hijacked: bool
    iteration_limit_reached: bool
    reads: tuple[str, ...] = ()


class Agent:
    """Runs a workload one step at a time under a :class:`RuntimeGuard`."""

    def __init__(
        self,
        model: object,
        tools: MockToolset | None = None,
        *,
        max_steps: int = AGENT_MAX_STEPS,
    ) -> None:
        for method in ("render", "count_tokens", "generate"):
            if not hasattr(model, method):
                raise TypeError(f"model must provide {method}().")
        _count(max_steps, "max_steps", minimum=1)
        self.model = model
        self.tools = tools or MockToolset()
        self.max_steps = max_steps
        self.transcript: list[str] = []

    def run(self, workload: Workload, guard: RuntimeGuard) -> AgentRun:
        if not guard.active:
            raise RuntimeError("Open a guard session before running the agent.")
        self.transcript = []
        self._read: list[str] = []
        hijacked = False
        iteration_limit = False
        for request_index in range(workload.requests):
            if request_index == 0 or workload.requests > 1:
                self.transcript.append(f"user: {workload.task}")
            try:
                guard.before_request()
            except GuardError as exc:
                self.transcript.append(
                    f"guard: refused the next request ({exc.kind.value})"
                )
                return self._partial(exc.kind.value, hijacked, iteration_limit)
            context = initial_context_tokens(workload.task)
            guard.observe_context(context)
            obeying = asks_to_keep_going(workload.task)
            self._next_page = 1
            index = 0
            try:
                while True:
                    planned = self.max_steps if obeying else workload.iterations_per_request
                    if index >= min(planned, self.max_steps):
                        break
                    context, told = self._run_iteration(
                        workload, guard, context, index, obeying
                    )
                    if told and not obeying:
                        obeying = True
                        hijacked = True
                        self.transcript.append(
                            "decision: The note says to keep searching until I am sure. "
                            "I will do what it says."
                        )
                    index += 1
            except GuardError as exc:
                self.transcript.append(
                    f"guard: refused the next step ({exc.kind.value})"
                )
                return self._partial(exc.kind.value, hijacked, iteration_limit)
            if obeying or workload.iterations_per_request > self.max_steps:
                iteration_limit = True
                self.transcript.append(
                    f"agent: reached its own iteration limit ({self.max_steps} model calls) "
                    "and is still not sure."
                )
                break
            guard.record_request_completed()
        if iteration_limit:
            return self._partial("iteration limit", hijacked, iteration_limit)
        answer = (
            f"answer: Read {', '.join(self._read_unique()) or 'no notes'}. "
            "The answer is ready (fixed classroom text)."
        )
        self.transcript.append(answer)
        return AgentRun(
            answer=answer,
            answer_status="complete",
            stopped_by="completed",
            hijacked=hijacked,
            iteration_limit_reached=False,
            reads=tuple(self._read),
        )

    def _read_unique(self) -> list[str]:
        seen: list[str] = []
        for label in self._read:
            if label not in seen:
                seen.append(label)
        return seen

    def _partial(self, reason: str, hijacked: bool, iteration_limit: bool) -> AgentRun:
        read = ", ".join(self._read_unique()) or "nothing yet"
        answer = (
            f"answer (partial): Stopped by {reason}. Returning what was read so far: "
            f"{read}. The rest of the plan did not run."
        )
        self.transcript.append(answer)
        return AgentRun(
            answer=answer,
            answer_status="partial",
            stopped_by=reason,
            hijacked=hijacked,
            iteration_limit_reached=iteration_limit,
            reads=tuple(self._read),
        )

    def _calls_for(
        self, workload: Workload, index: int, obeying: bool
    ) -> tuple[ToolCall, ...]:
        target = workload.notes[0] if len(workload.notes) == 1 else DEFAULT_NOTE
        if obeying:
            return (
                ToolCall("search_notes", page=self._next_page),
                ToolCall("read_note", target, self._next_page),
            )
        if len(workload.notes) > 1:
            base: tuple[ToolCall, ...] = (
                ToolCall("read_note", workload.notes[index % len(workload.notes)]),
            )
        else:
            base = (
                ToolCall("search_notes", page=self._next_page),
                ToolCall("read_note", target, self._next_page),
            )
        return tuple(base[offset % len(base)] for offset in range(workload.tool_calls_per_iteration))

    def _run_iteration(
        self,
        workload: Workload,
        guard: RuntimeGuard,
        context: int,
        index: int,
        obeying: bool,
    ) -> tuple[int, bool]:
        calls = self._calls_for(workload, index, obeying)
        guard.before_iteration()
        self.transcript.append(
            "decision: "
            + thought_for(
                workload,
                index,
                obeying=obeying,
                calls=tuple(call.label() for call in calls),
            )
        )
        prompt = self.model.render(context, workload.task)
        input_tokens = self.model.count_tokens(prompt)
        guard.before_model(input_tokens, workload.max_new_tokens)
        output = self.model.generate(prompt, workload.max_new_tokens)
        if not isinstance(output, ModelOutput):
            output = ModelOutput(
                text=str(getattr(output, "text", "")),
                input_tokens=int(output.input_tokens),
                output_tokens=int(output.output_tokens),
            )
        guard.record_model(output.input_tokens, output.output_tokens)
        guard.record_iteration()
        context = output.input_tokens + output.output_tokens
        guard.observe_context(context)
        self.transcript.append(
            f"model: read {output.input_tokens} tokens, wrote {output.output_tokens}"
        )
        told = False
        for call in calls:
            size = self.tools.result_tokens(call, workload.context_pad_tokens)
            guard.before_context_growth(context + size)
            guard.before_tool_call()
            result = self.tools.invoke(call, size)
            added = self.model.count_tokens(result.content)
            guard.record_tool_call(result.name, result.content)
            context += added
            guard.observe_context(context)
            self._observe(result, added, context)
            if result.next_page is not None:
                self._next_page = result.next_page
            if call.name == "read_note" and asks_to_keep_going(result.content):
                told = True
        guard.end_iteration()
        return context, told

    def _observe(self, result: ToolResult, added: int, context: int) -> None:
        if result.name == "read_note":
            self._read.append(result.label.removeprefix("read_note(").removesuffix(")"))
        self.transcript.append(f"action: {result.label}")
        self.transcript.append(
            f"observe: {result.summary} (+{added} tokens, transcript {context})"
        )
