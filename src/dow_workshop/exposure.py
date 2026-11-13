"""Arithmetic for an agent you describe yourself. Nothing runs.

The notebook measures a classroom agent. This module answers the follow-up
question: what would the same loop cost in an agent with your iteration limit, your
tool results and your prices? It is a projection from the numbers you type,
and it always carries the disclaimer.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from dow_workshop.config import COST_DISCLAIMER, DEFAULT_RATES, IllustrativeRates
from dow_workshop.metrics import cost_micro_usd, format_usd


@dataclass(frozen=True)
class LoopProjection:
    """One request that runs for ``model_calls`` steps."""

    model_calls: int
    tool_calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    largest_prompt: int
    cost_micro_usd: int


def _whole(value: object, name: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be a whole number.")
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum:,} and {maximum:,}.")
    return value


def project_loop(
    model_calls: int,
    *,
    first_prompt_tokens: int,
    tool_text_tokens_per_step: int,
    output_tokens_per_call: int,
    tool_calls_per_step: int,
    context_window_tokens: int | None = None,
    rates: IllustrativeRates | None = None,
) -> LoopProjection:
    """Tokens and illustrative cost of one request that loops.

    Each call reads the whole transcript. Each step then adds the model's reply
    and the tool text. If a context window is given, a prompt never grows past
    it: once the window is full, every further call re-reads a full window.
    """

    calls = _whole(model_calls, "model_calls", minimum=1, maximum=100_000)
    first = _whole(first_prompt_tokens, "first_prompt_tokens", minimum=1, maximum=10_000_000)
    tool_text = _whole(
        tool_text_tokens_per_step, "tool_text_tokens_per_step", minimum=0, maximum=10_000_000
    )
    reply = _whole(
        output_tokens_per_call, "output_tokens_per_call", minimum=1, maximum=1_000_000
    )
    tools = _whole(tool_calls_per_step, "tool_calls_per_step", minimum=0, maximum=1_000)
    window = None
    if context_window_tokens is not None:
        window = _whole(
            context_window_tokens, "context_window_tokens", minimum=1, maximum=100_000_000
        )
    input_tokens = 0
    largest = 0
    prompt = first
    for _call in range(calls):
        size = prompt if window is None else min(prompt, window)
        input_tokens += size
        largest = max(largest, size)
        prompt += reply + tool_text
    output_tokens = calls * reply
    tool_calls = calls * tools
    return LoopProjection(
        model_calls=calls,
        tool_calls=tool_calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        largest_prompt=largest,
        cost_micro_usd=cost_micro_usd(input_tokens, output_tokens, tool_calls, rates),
    )


@dataclass(frozen=True)
class Exposure:
    """A normal run, a hijacked run, and the same day with a per-run budget."""

    normal: LoopProjection
    hijacked: LoopProjection
    capped: LoopProjection
    requests_per_day: int
    budget_multiple: int

    @property
    def token_multiplier(self) -> float:
        return self.hijacked.total_tokens / max(1, self.normal.total_tokens)

    @property
    def normal_day_micro_usd(self) -> int:
        return self.normal.cost_micro_usd * self.requests_per_day

    @property
    def hijacked_day_micro_usd(self) -> int:
        return self.hijacked.cost_micro_usd * self.requests_per_day

    @property
    def capped_day_micro_usd(self) -> int:
        return self.capped.cost_micro_usd * self.requests_per_day


def estimate_exposure(
    *,
    iteration_limit: int,
    normal_steps: int = 1,
    first_prompt_tokens: int,
    tool_text_tokens_per_step: int,
    output_tokens_per_call: int,
    tool_calls_per_step: int,
    requests_per_day: int,
    budget_multiple: int = 3,
    context_window_tokens: int | None = None,
    rates: IllustrativeRates | None = None,
) -> Exposure:
    """Compare a normal run with one that loops to the iteration limit.

    ``budget_multiple`` models the simplest defence: a per-run token budget set
    to that many times the normal run. The capped run is the longest loop whose
    total tokens stay inside it.
    """

    cap = _whole(iteration_limit, "iteration_limit", minimum=1, maximum=100_000)
    usual = _whole(normal_steps, "normal_steps", minimum=1, maximum=100_000)
    if usual > cap:
        raise ValueError("normal_steps cannot be larger than iteration_limit.")
    per_day = _whole(requests_per_day, "requests_per_day", minimum=1, maximum=100_000_000)
    multiple = _whole(budget_multiple, "budget_multiple", minimum=1, maximum=1_000)
    shape = {
        "first_prompt_tokens": first_prompt_tokens,
        "tool_text_tokens_per_step": tool_text_tokens_per_step,
        "output_tokens_per_call": output_tokens_per_call,
        "tool_calls_per_step": tool_calls_per_step,
        "context_window_tokens": context_window_tokens,
        "rates": rates,
    }
    normal = project_loop(usual, **shape)  # type: ignore[arg-type]
    hijacked = project_loop(cap, **shape)  # type: ignore[arg-type]
    budget = normal.total_tokens * multiple
    capped = normal
    for calls in range(usual, cap + 1):
        candidate = project_loop(calls, **shape)  # type: ignore[arg-type]
        if candidate.total_tokens > budget:
            break
        capped = candidate
    return Exposure(
        normal=normal,
        hijacked=hijacked,
        capped=capped,
        requests_per_day=per_day,
        budget_multiple=multiple,
    )


def _plain(rate: object) -> str:
    """A rate without trailing zeros or an exponent: 3, 15, 0.005."""

    return format(Decimal(str(rate)).normalize(), "f")


def format_exposure(exposure: Exposure, rates: IllustrativeRates | None = None) -> str:
    card = rates or DEFAULT_RATES
    rows = (
        ("A normal run", exposure.normal, exposure.normal_day_micro_usd),
        ("A run that loops to your iteration limit", exposure.hijacked, exposure.hijacked_day_micro_usd),
        (
            f"The same loop, stopped by a budget of {exposure.budget_multiple}× a normal run",
            exposure.capped,
            exposure.capped_day_micro_usd,
        ),
    )
    width = max(len(label) for label, _run, _day in rows)
    lines = [
        "Your agent, from the numbers you typed (a projection, nothing ran):",
        "",
        f"  {'':<{width}}  {'model calls':>11}  {'tokens':>14}  {'USD per run':>12}  "
        f"{'USD per day':>14}",
    ]
    for label, run, day in rows:
        lines.append(
            f"  {label:<{width}}  {run.model_calls:>11,}  {run.total_tokens:>14,}  "
            f"{format_usd(run.cost_micro_usd, 4):>12}  {format_usd(day):>14}"
        )
    lines.append("")
    lines.append(
        f"One tampered document turns each request into {exposure.token_multiplier:,.0f}× "
        f"the tokens. The iteration limit decides that number, and the attacker gets all of it."
    )
    lines.append(
        f"Per day assumes all {exposure.requests_per_day:,} requests read the tampered "
        "document. Scale it down by the share that would."
    )
    lines.append(
        f"Rates used: {_plain(card.input_usd_per_million_tokens)} USD per million input "
        f"tokens, {_plain(card.output_usd_per_million_tokens)} per million output tokens, "
        f"{_plain(card.usd_per_tool_call)} per tool call."
    )
    lines.append(
        "Not modelled: prompt caching, which makes re-read tokens cheaper without "
        "changing the shape of the curve, and context compaction."
    )
    lines.append(COST_DISCLAIMER)
    return "\n".join(lines)
