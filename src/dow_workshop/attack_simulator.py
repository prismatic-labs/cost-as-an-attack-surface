"""Controlled amplification inside the local sandbox.

The user's request is benign. One of the local notes carries an instruction
aimed at the assistant, and the agent obeys it. The simulator runs that loop
under different policies and measures what was spent and what was refused.
It does not open sockets, scan addresses, or send traffic anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from dow_workshop.agent import Agent, Workload
from dow_workshop.config import (
    AGENT_MAX_STEPS,
    BUDGET_POLICY,
    DEFAULT_CEILINGS,
    DEFAULT_RATES,
    DEFAULT_TASK,
    LONG_TASK,
    LONGER_TASK,
    PROGRESS_POLICY,
    RECHECK_TASK,
    GuardPolicy,
    IllustrativeRates,
    SafetyCeilings,
    sandbox_policy,
)
from dow_workshop.metrics import (
    ExecutionMetrics,
    cost_micro_usd,
    estimate_cost,
    format_comparison,
    format_usd,
    format_usd_micro,
    initial_context_tokens,
    process_peak_rss_bytes,
)
from dow_workshop.mock_tools import MockToolset
from dow_workshop.model import DeterministicModel
from dow_workshop.planner import plan_from_prompt
from dow_workshop.runtime_guard import RuntimeGuard


NORMAL_WORKLOAD = plan_from_prompt(DEFAULT_TASK).workload
LONG_WORKLOAD = plan_from_prompt(LONG_TASK).workload
LONGER_WORKLOAD = plan_from_prompt(LONGER_TASK).workload
RECHECK_WORKLOAD = plan_from_prompt(RECHECK_TASK).workload
# What the hijacked agent ends up doing: the normal plan, repeated to the iteration limit.
HIJACKED_WORKLOAD = replace(
    NORMAL_WORKLOAD, name="hijacked", iterations_per_request=AGENT_MAX_STEPS
)

SCENARIO_NORMAL = "Normal request"
SCENARIO_POISONED = "Poisoned note, no policy"
SCENARIO_BUDGET = "Poisoned note, budget"
SCENARIO_LONG_BUDGET = "Long task, budget"
SCENARIO_PROGRESS = "Poisoned note, progress check"
SCENARIO_LONG_PROGRESS = "Long task, progress check"

GROWTH_STEPS: tuple[int, ...] = (10, 20, 40, 80)
GROWTH_REQUESTS = 10_000


@dataclass(frozen=True)
class Projection:
    """Token and cost totals implied by a uniform schedule. Nothing runs."""

    iterations: int
    tool_calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    max_context_tokens: int
    cost_micro_usd: int
    input_sizes: tuple[int, ...]


def iteration_input_sizes(workload: Workload) -> tuple[int, ...]:
    """Prompt size at each model call of a single request.

    Each step re-reads the transcript, then appends the model reply and the
    tool text. The sizes are an arithmetic sequence, so the token total grows
    with the square of the step count.
    """

    sizes: list[int] = []
    context = initial_context_tokens(workload.task)
    step = workload.max_new_tokens + (
        workload.tool_calls_per_iteration * workload.context_pad_tokens
    )
    for _iteration in range(workload.iterations_per_request):
        sizes.append(context)
        context += step
    return tuple(sizes)


def project_workload(
    workload: Workload, rates: IllustrativeRates | None = None
) -> Projection:
    """Arithmetic projection of a uniform schedule. No model or tool is called."""

    sizes = iteration_input_sizes(workload)
    input_tokens = sum(sizes) * workload.requests
    output_tokens = (
        workload.requests * workload.iterations_per_request * workload.max_new_tokens
    )
    tool_calls = (
        workload.requests
        * workload.iterations_per_request
        * workload.tool_calls_per_iteration
    )
    growth = workload.max_new_tokens + (
        workload.tool_calls_per_iteration * workload.context_pad_tokens
    )
    return Projection(
        iterations=workload.requests * workload.iterations_per_request,
        tool_calls=tool_calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        max_context_tokens=(sizes[-1] + growth) if sizes else 0,
        cost_micro_usd=cost_micro_usd(input_tokens, output_tokens, tool_calls, rates),
        input_sizes=sizes,
    )


def growth_table(
    steps: tuple[int, ...] = GROWTH_STEPS,
    workload: Workload = HIJACKED_WORKLOAD,
    rates: IllustrativeRates | None = None,
) -> list[Projection]:
    """The hijacked loop at longer iteration limits. Arithmetic only, nothing runs."""

    return [
        project_workload(replace(workload, iterations_per_request=count), rates)
        for count in steps
    ]


def format_growth_table(
    rows: list[Projection] | None = None, *, requests: int = GROWTH_REQUESTS
) -> str:
    rows = rows if rows is not None else growth_table()
    lines = [
        "One hijacked request at longer iteration limits (projection, nothing runs):",
        f"  {'model calls':>11}  {'total tokens':>12}  {'USD per request':>15}  "
        f"{f'USD per {requests:,} requests':>26}",
    ]
    for row in rows:
        lines.append(
            f"  {row.iterations:>11}  {row.total_tokens:>12,}  "
            f"{format_usd(row.cost_micro_usd, 4):>15}  "
            f"{format_usd(row.cost_micro_usd * requests):>26}"
        )
    lines.append(
        "Double the model calls and the tokens roughly quadruple: each call "
        "re-reads everything before it."
    )
    lines.append("ILLUSTRATIVE SIMULATED COST. NOT AN ACTUAL API BILL.")
    return "\n".join(lines)


def clamp_workload(
    workload: Workload, ceilings: SafetyCeilings | None = None
) -> tuple[Workload, tuple[str, ...]]:
    """Shrink a requested schedule until it fits the hard safety ceilings."""

    limits = ceilings or DEFAULT_CEILINGS
    warnings: list[str] = []

    def cut(name: str, value: int, ceiling: int) -> int:
        if value > ceiling:
            warnings.append(
                f"{name} reduced from {value} to the hard safety ceiling {ceiling}."
            )
            return ceiling
        return value

    requests = cut("requests", workload.requests, limits.max_requests)
    iterations = cut(
        "iterations_per_request", workload.iterations_per_request, limits.max_iterations
    )
    if requests * iterations > limits.max_iterations:
        reduced = max(1, limits.max_iterations // requests)
        warnings.append(
            "iterations_per_request reduced from "
            f"{iterations} to {reduced} so that requests × iterations "
            f"stays within the hard safety ceiling of {limits.max_iterations}."
        )
        iterations = reduced
    tools = cut(
        "tool_calls_per_iteration", workload.tool_calls_per_iteration, limits.max_tool_calls
    )
    product = requests * iterations
    if product > 0 and product * tools > limits.max_tool_calls:
        reduced_tools = limits.max_tool_calls // product
        warnings.append(
            "tool_calls_per_iteration reduced from "
            f"{tools} to {reduced_tools} so that total tool calls stay within "
            f"the hard safety ceiling of {limits.max_tool_calls}."
        )
        tools = reduced_tools
    pad = workload.context_pad_tokens
    if tools > 0:
        pad = cut("context_pad_tokens", pad, limits.max_context_pad_tokens)
    new_tokens = cut(
        "max_new_tokens", workload.max_new_tokens, limits.max_output_tokens_per_step
    )
    notes = workload.notes
    if len(notes) > 1 and len(notes) > iterations:
        notes = notes[:iterations]
    schedule = replace(
        workload,
        requests=requests,
        iterations_per_request=iterations,
        tool_calls_per_iteration=tools,
        context_pad_tokens=pad,
        max_new_tokens=new_tokens,
        notes=notes,
    )
    return schedule, tuple(warnings)


@dataclass(frozen=True)
class ExperimentResult:
    scenario: str
    notes: str
    requested: Workload
    schedule: Workload
    metrics: ExecutionMetrics
    events: tuple[str, ...]
    transcript: tuple[str, ...] = ()
    plan_reason: str = ""
    answer: str = ""
    call_tokens: tuple[tuple[int, int], ...] = ()
    reads: tuple[str, ...] = ()

    @property
    def prompt_sizes(self) -> tuple[int, ...]:
        """Measured prompt size at each model call."""

        return tuple(inputs for inputs, _outputs in self.call_tokens)

    def summary(self) -> str:
        m = self.metrics
        lines = [
            self.scenario,
            f"prompt: {self.schedule.task}",
            f"notes: {self.notes}",
            f"requests started: {m.requests_started}",
            f"model calls: {m.model_calls}",
            f"tool calls: {m.tool_calls}",
            f"input tokens: {m.input_tokens:,}",
            f"output tokens: {m.output_tokens:,}",
            f"total tokens: {m.total_tokens:,}",
            f"peak context: {m.max_context_tokens:,} tokens "
            f"(largest prompt: {max(self.prompt_sizes, default=0):,})",
            f"illustrative cost USD: {format_usd_micro(m.illustrative_cost_micro_usd)}",
            m.cost_disclaimer,
            f"stopped by: {m.stopped_by}",
            f"answer: {m.answer_status}",
        ]
        if self.plan_reason:
            lines.insert(2, f"plan: {self.plan_reason}")
        if m.hijacked:
            lines.append("The agent followed an instruction it found inside a note.")
        if m.prevented_total_tokens:
            lines.append(
                "refused before it ran, against the same run with no policy: "
                f"{m.prevented_iterations} model calls, "
                f"{m.prevented_tool_calls} tool calls, "
                f"{m.prevented_total_tokens:,} tokens, "
                f"illustrative {format_usd_micro(m.prevented_cost_micro_usd)} USD"
            )
        if m.warnings:
            lines.append("warnings:")
            lines.extend(f"- {warning}" for warning in m.warnings)
        return "\n".join(lines)


def _execute(
    schedule: Workload,
    notes: str,
    model: object,
    policy: GuardPolicy,
    limits: SafetyCeilings,
    card: IllustrativeRates,
    clock: object | None,
    max_steps: int,
) -> tuple[RuntimeGuard, Agent, object]:
    guard = RuntimeGuard(policy=policy, ceilings=limits, rates=card, clock=clock)  # type: ignore[arg-type]
    agent = Agent(model, MockToolset(notes), max_steps=max_steps)
    with guard.session():
        outcome = agent.run(schedule, guard)
    return guard, agent, outcome


def run_session(
    workload: Workload,
    *,
    notes: str = "clean",
    model: object | None = None,
    policy: GuardPolicy | None = None,
    ceilings: SafetyCeilings | None = None,
    rates: IllustrativeRates | None = None,
    clock: object | None = None,
    scenario_name: str | None = None,
    max_steps: int = AGENT_MAX_STEPS,
) -> ExperimentResult:
    """Run one clamped schedule under a runtime guard.

    ``policy`` is the configurable budget. The hard ceiling still applies when
    the policy is left at the sandbox maximum. The "refused" figures compare the
    run with the same agent on the same notes under the sandbox policy alone.
    """

    limits = ceilings or DEFAULT_CEILINGS
    card = rates or DEFAULT_RATES
    chosen = model or DeterministicModel()
    schedule, clamp_warnings = clamp_workload(workload, limits)
    label = scenario_name or schedule.name
    guard, agent, outcome = _execute(
        schedule, notes, chosen, policy or sandbox_policy(limits), limits, card, clock, max_steps
    )
    reference, _agent, _outcome = _execute(
        schedule,
        notes,
        DeterministicModel(),
        sandbox_policy(limits),
        limits,
        card,
        lambda: 0.0,
        max_steps,
    )
    measured = estimate_cost(guard.input_tokens, guard.output_tokens, guard.tool_calls, card)
    planned_cost = cost_micro_usd(
        reference.input_tokens, reference.output_tokens, reference.tool_calls, card
    )
    metrics = ExecutionMetrics(
        scenario=label,
        requests_started=guard.requests_started,
        requests_completed=guard.requests_completed,
        iterations=guard.iterations,
        model_calls=guard.model_calls,
        tool_calls=guard.tool_calls,
        input_tokens=guard.input_tokens,
        output_tokens=guard.output_tokens,
        total_tokens=guard.total_tokens,
        max_context_tokens=guard.max_context_tokens,
        duration_seconds=guard.elapsed_seconds(),
        process_peak_rss_bytes=process_peak_rss_bytes(),
        illustrative_cost_micro_usd=measured.total_micro_usd,
        illustrative_input_micro_usd=measured.input_micro_usd,
        illustrative_output_micro_usd=measured.output_micro_usd,
        illustrative_tool_micro_usd=measured.tool_micro_usd,
        planned_iterations=reference.iterations,
        planned_tool_calls=reference.tool_calls,
        planned_input_tokens=reference.input_tokens,
        planned_output_tokens=reference.output_tokens,
        planned_total_tokens=reference.total_tokens,
        planned_cost_micro_usd=planned_cost,
        prevented_iterations=max(0, reference.iterations - guard.iterations),
        prevented_tool_calls=max(0, reference.tool_calls - guard.tool_calls),
        prevented_total_tokens=max(0, reference.total_tokens - guard.total_tokens),
        prevented_cost_micro_usd=max(0, planned_cost - measured.total_micro_usd),
        stop_reason=guard.stop_reason,
        limit_kind=None if guard.limit_kind is None else guard.limit_kind.value,
        circuit_open=guard.tripped,
        backend_name=str(getattr(chosen, "name", type(chosen).__name__)),
        stopped_by=outcome.stopped_by,  # type: ignore[attr-defined]
        answer_status=outcome.answer_status,  # type: ignore[attr-defined]
        hijacked=outcome.hijacked,  # type: ignore[attr-defined]
        warnings=tuple(clamp_warnings) + tuple(guard.warnings),
    )
    return ExperimentResult(
        scenario=label,
        notes=notes,
        requested=workload,
        schedule=schedule,
        metrics=metrics,
        events=tuple(guard.events),
        transcript=tuple(agent.transcript),
        plan_reason=plan_from_prompt(schedule.task).reason,
        answer=outcome.answer,  # type: ignore[attr-defined]
        call_tokens=tuple(guard.call_log),
        reads=tuple(outcome.reads),  # type: ignore[attr-defined]
    )


def run_from_prompt(prompt: str, **kwargs: object) -> ExperimentResult:
    """Build a plan from a prompt, then run it."""

    return run_session(plan_from_prompt(prompt).workload, **kwargs)  # type: ignore[arg-type]


def compare_scenarios(
    rates: IllustrativeRates | None = None,
    ceilings: SafetyCeilings | None = None,
) -> tuple[ExperimentResult, ...]:
    """The six workshop rows, in teaching order."""

    shared = {"rates": rates, "ceilings": ceilings}
    loose = sandbox_policy(ceilings)
    return (
        run_session(NORMAL_WORKLOAD, policy=loose, scenario_name=SCENARIO_NORMAL, **shared),  # type: ignore[arg-type]
        run_session(
            NORMAL_WORKLOAD, notes="poisoned", policy=loose, scenario_name=SCENARIO_POISONED, **shared  # type: ignore[arg-type]
        ),
        run_session(
            NORMAL_WORKLOAD, notes="poisoned", policy=BUDGET_POLICY, scenario_name=SCENARIO_BUDGET, **shared  # type: ignore[arg-type]
        ),
        run_session(
            LONG_WORKLOAD, policy=BUDGET_POLICY, scenario_name=SCENARIO_LONG_BUDGET, **shared  # type: ignore[arg-type]
        ),
        run_session(
            NORMAL_WORKLOAD, notes="poisoned", policy=PROGRESS_POLICY, scenario_name=SCENARIO_PROGRESS, **shared  # type: ignore[arg-type]
        ),
        run_session(
            LONG_WORKLOAD, policy=PROGRESS_POLICY, scenario_name=SCENARIO_LONG_PROGRESS, **shared  # type: ignore[arg-type]
        ),
    )


def amplification_note(normal: ExperimentResult, poisoned: ExperimentResult) -> str:
    normal_tokens = max(1, normal.metrics.total_tokens)
    factor = poisoned.metrics.total_tokens / normal_tokens
    return (
        f"Same user request. Requests started: {normal.metrics.requests_started} → "
        f"{poisoned.metrics.requests_started}. "
        f"Total tokens: {normal.metrics.total_tokens:,} → "
        f"{poisoned.metrics.total_tokens:,} (×{factor:.0f}). "
        "The only difference was one note. It told the agent to keep searching, "
        "and the agent did, until its own iteration limit. The attacker never sent a request."
    )


def format_report(
    results: tuple[ExperimentResult, ...] | list[ExperimentResult],
    *,
    include_duration: bool = False,
) -> str:
    return format_comparison(
        [item.metrics for item in results], include_duration=include_duration
    )
