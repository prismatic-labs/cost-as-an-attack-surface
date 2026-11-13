"""Measured resource use, separate from illustrative money.

Real measurements are counts and durations produced by the local run.
Simulated measurements apply the synthetic rate card and always carry the
disclaimer. Nothing here represents an invoice from a model provider.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from dow_workshop.config import (
    COST_DISCLAIMER,
    DEFAULT_RATES,
    INITIAL_CONTEXT_TOKENS,
    OPERATIONAL_LIMITATIONS,
    IllustrativeRates,
)


def process_peak_rss_bytes() -> int | None:
    """Best-effort process peak resident set size.

    On macOS ``ru_maxrss`` is bytes. On Linux it is kilobytes. The value is
    the process peak, not the bytes allocated by one experiment.
    """

    try:
        import resource

        rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except (ImportError, AttributeError, ValueError, OSError):
        return None
    if rss < 0:
        return None
    if sys.platform == "darwin":
        return rss
    return rss * 1024


def estimate_tokens(text: str) -> int:
    """Estimate tokens as one per four characters.

    This is a workshop convention so every attendee can reproduce the same
    counts without a tokenizer. It is not a claim about any provider's
    tokeniser. Empty text is zero tokens.
    """

    if not isinstance(text, str):
        raise TypeError("text must be a string.")
    if text == "":
        return 0
    return (len(text) + 3) // 4


def text_with_token_count(target: int, prefix: str) -> str:
    """Build text whose :func:`estimate_tokens` count is exactly ``target``."""

    if isinstance(target, bool) or not isinstance(target, int):
        raise ValueError("target token count must be an integer.")
    if target < 1 or target > 100_000:
        raise ValueError("target token count must be between 1 and 100000.")
    length = 4 * target - 3
    head = (prefix or "Note").strip()
    if len(head) > length:
        head = head[:length]
    if len(head) < length:
        pad = length - len(head)
        unit = " note"
        filler = (unit * ((pad // len(unit)) + 1))[:pad]
        head = f"{head}{filler}"
    text = head[:length]
    if len(text) < length:
        text = text + ("x" * (length - len(text)))
    if estimate_tokens(text) != target:
        raise RuntimeError("Token fitter could not hit the requested count.")
    return text


def initial_context_tokens(task: str) -> int:
    """Token size of the prompt at the start of each user request."""

    if not isinstance(task, str) or not task.strip():
        raise ValueError("task must be a non-empty string.")
    needed = estimate_tokens(task.strip()) + 16
    return max(INITIAL_CONTEXT_TOKENS, needed)


def cost_micro_usd(
    input_tokens: int,
    output_tokens: int,
    tool_calls: int,
    rates: IllustrativeRates | None = None,
) -> int:
    """Return the illustrative cost in integer micro-USD (millionths of a USD).

    The arithmetic is decimal, not binary floating point:
    micro-USD = input_tokens * input_rate
                + output_tokens * output_rate
                + tool_calls * tool_rate * 1_000_000
    where rates are USD per million tokens, or USD per tool call.
    """

    card = rates or DEFAULT_RATES
    for name, value in (
        ("input_tokens", input_tokens),
        ("output_tokens", output_tokens),
        ("tool_calls", tool_calls),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer.")
    micro = (
        Decimal(input_tokens) * card.input_usd_per_million_tokens
        + Decimal(output_tokens) * card.output_usd_per_million_tokens
        + Decimal(tool_calls) * card.usd_per_tool_call * Decimal(1_000_000)
    )
    return int(micro.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def format_usd_micro(micro: int) -> str:
    """Format micro-USD as a fixed six-decimal USD string."""

    if isinstance(micro, bool) or not isinstance(micro, int):
        raise ValueError("micro-USD must be an integer.")
    sign = "-" if micro < 0 else ""
    value = abs(micro)
    return f"{sign}{value // 1_000_000}.{value % 1_000_000:06d}"


def format_usd(micro: int, places: int = 2) -> str:
    """Round micro-USD for reading: thousands separators, ``places`` decimals."""

    if isinstance(micro, bool) or not isinstance(micro, int):
        raise ValueError("micro-USD must be an integer.")
    value = (Decimal(micro) / Decimal(1_000_000)).quantize(
        Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP
    )
    return f"{value:,.{places}f}"


@dataclass(frozen=True)
class CostBreakdown:
    """Illustrative cost parts. Every figure carries the disclaimer."""

    input_micro_usd: int
    output_micro_usd: int
    tool_micro_usd: int
    total_micro_usd: int
    disclaimer: str = COST_DISCLAIMER

    @property
    def total_display(self) -> str:
        return format_usd_micro(self.total_micro_usd)

    def as_dict(self) -> dict[str, object]:
        return {
            "disclaimer": self.disclaimer,
            "input_usd": format_usd_micro(self.input_micro_usd),
            "output_usd": format_usd_micro(self.output_micro_usd),
            "tool_usd": format_usd_micro(self.tool_micro_usd),
            "total_usd": self.total_display,
            "total_micro_usd": self.total_micro_usd,
        }


def estimate_cost(
    input_tokens: int,
    output_tokens: int,
    tool_calls: int,
    rates: IllustrativeRates | None = None,
) -> CostBreakdown:
    card = rates or DEFAULT_RATES
    input_micro = cost_micro_usd(input_tokens, 0, 0, card)
    output_micro = cost_micro_usd(0, output_tokens, 0, card)
    tool_micro = cost_micro_usd(0, 0, tool_calls, card)
    return CostBreakdown(
        input_micro_usd=input_micro,
        output_micro_usd=output_micro,
        tool_micro_usd=tool_micro,
        total_micro_usd=input_micro + output_micro + tool_micro,
    )


@dataclass(frozen=True)
class ExecutionMetrics:
    """One scenario's measurements, split into real and simulated groups."""

    scenario: str
    requests_started: int
    requests_completed: int
    iterations: int
    model_calls: int
    tool_calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    max_context_tokens: int
    duration_seconds: float
    process_peak_rss_bytes: int | None
    illustrative_cost_micro_usd: int
    illustrative_input_micro_usd: int
    illustrative_output_micro_usd: int
    illustrative_tool_micro_usd: int
    planned_iterations: int
    planned_tool_calls: int
    planned_input_tokens: int
    planned_output_tokens: int
    planned_total_tokens: int
    planned_cost_micro_usd: int
    prevented_iterations: int
    prevented_tool_calls: int
    prevented_total_tokens: int
    prevented_cost_micro_usd: int
    stop_reason: str | None
    limit_kind: str | None
    circuit_open: bool
    backend_name: str
    stopped_by: str = "completed"
    answer_status: str = "complete"
    hijacked: bool = False
    warnings: tuple[str, ...] = ()
    cost_disclaimer: str = COST_DISCLAIMER

    def grouped(self) -> dict[str, object]:
        return {
            "scenario": self.scenario,
            "real_measurements": {
                "requests_started": self.requests_started,
                "requests_completed": self.requests_completed,
                "iterations": self.iterations,
                "model_calls": self.model_calls,
                "tool_calls": self.tool_calls,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "total_tokens": self.total_tokens,
                "max_context_tokens": self.max_context_tokens,
                "duration_seconds": round(self.duration_seconds, 6),
                "process_peak_rss_bytes": self.process_peak_rss_bytes,
                "backend": self.backend_name,
            },
            "simulated_measurements": {
                "disclaimer": self.cost_disclaimer,
                "illustrative_cost_usd": format_usd_micro(
                    self.illustrative_cost_micro_usd
                ),
                "illustrative_input_usd": format_usd_micro(
                    self.illustrative_input_micro_usd
                ),
                "illustrative_output_usd": format_usd_micro(
                    self.illustrative_output_micro_usd
                ),
                "illustrative_tool_usd": format_usd_micro(
                    self.illustrative_tool_micro_usd
                ),
                "projected_schedule_cost_usd": format_usd_micro(
                    self.planned_cost_micro_usd
                ),
                "illustrative_cost_avoided_usd": format_usd_micro(
                    self.prevented_cost_micro_usd
                ),
            },
            "schedule_projection": {
                "note": (
                    "What the same agent does on the same notes with no policy "
                    "beyond the sandbox ceiling."
                ),
                "iterations": self.planned_iterations,
                "tool_calls": self.planned_tool_calls,
                "input_tokens": self.planned_input_tokens,
                "output_tokens": self.planned_output_tokens,
                "total_tokens": self.planned_total_tokens,
            },
            "prevention": {
                "iterations": self.prevented_iterations,
                "tool_calls": self.prevented_tool_calls,
                "total_tokens": self.prevented_total_tokens,
                "stop_reason": self.stop_reason,
                "limit_kind": self.limit_kind,
                "stopped_by": self.stopped_by,
                "answer_status": self.answer_status,
                "hijacked": self.hijacked,
                "circuit_open": self.circuit_open,
            },
            "operational_limitations": list(OPERATIONAL_LIMITATIONS),
            "warnings": list(self.warnings),
        }

    @property
    def illustrative_cost_usd_for_chart(self) -> float:
        """Float view for bar charts. The exact figure is the micro-USD field."""

        return self.illustrative_cost_micro_usd / 1_000_000


def comparison_rows(metrics: list[ExecutionMetrics]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in metrics:
        rows.append(
            {
                "scenario": item.scenario,
                "requests_started": item.requests_started,
                "iterations": item.iterations,
                "tool_calls": item.tool_calls,
                "input_tokens": item.input_tokens,
                "output_tokens": item.output_tokens,
                "total_tokens": item.total_tokens,
                "duration_seconds": round(item.duration_seconds, 6),
                "illustrative_cost_usd": format_usd_micro(
                    item.illustrative_cost_micro_usd
                ),
                "tokens_avoided": item.prevented_total_tokens,
                "limit_kind": item.limit_kind or "",
                "stopped_by": item.stopped_by,
                "answer_status": item.answer_status,
                "disclaimer": item.cost_disclaimer,
            }
        )
    return rows


def format_comparison(
    metrics: list[ExecutionMetrics], *, include_duration: bool = False
) -> str:
    headers = [
        "scenario",
        "requests",
        "model calls",
        "tool calls",
        "total tokens",
        "illustrative USD",
        "stopped by",
        "answer",
    ]
    if include_duration:
        headers.insert(5, "seconds")
    body: list[tuple[str, ...]] = []
    for item in metrics:
        row = [
            item.scenario,
            str(item.requests_started),
            str(item.model_calls),
            str(item.tool_calls),
            f"{item.total_tokens:,}",
            format_usd_micro(item.illustrative_cost_micro_usd),
            item.stopped_by,
            item.answer_status,
        ]
        if include_duration:
            row.insert(5, f"{item.duration_seconds:.4f}")
        body.append(tuple(row))
    header_row = tuple(headers)
    widths = [
        max(len(header_row[index]), *(len(row[index]) for row in body))
        for index in range(len(header_row))
    ]

    def render(row: tuple[str, ...]) -> str:
        return "  ".join(part.ljust(widths[index]) for index, part in enumerate(row)).rstrip()

    lines = [render(header_row), render(tuple("-" * width for width in widths))]
    lines.extend(render(row) for row in body)
    lines.append(COST_DISCLAIMER)
    lines.append("Lead with tokens. The USD column is illustrative only.")
    if include_duration:
        lines.append(
            "Duration is measured wall-clock of this local run, not a hosted API latency."
        )
    else:
        lines.append(
            "Duration is omitted: the deterministic path is not a latency test."
        )
    return "\n".join(lines)
