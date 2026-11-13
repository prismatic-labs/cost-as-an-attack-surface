"""Runtime protection that refuses work before it starts.

A policy can be tighter than the hard safety ceiling. It cannot be looser.
Once any limit trips, the circuit stays open until ``reset`` and further
checks raise without performing another model call or tool call.
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Iterator

from dow_workshop.config import (
    COST_DISCLAIMER,
    DEFAULT_CEILINGS,
    DEFAULT_RATES,
    GuardPolicy,
    IllustrativeRates,
    SafetyCeilings,
    clamp_policy,
)
from dow_workshop.metrics import cost_micro_usd, estimate_cost, format_usd_micro


class LimitKind(str, Enum):
    ITERATIONS = "iterations"
    REQUESTS = "requests"
    TOKENS = "tokens"
    TOOL_CALLS = "tool_calls"
    CONTEXT = "context"
    TIME = "time"
    COST = "cost"
    NO_PROGRESS = "no_progress"
    CIRCUIT = "circuit"
    REENTRY = "reentry"


@dataclass(frozen=True)
class GuardSnapshot:
    iterations: int
    requests_started: int
    model_calls: int
    tool_calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    max_context_tokens: int
    elapsed_seconds: float
    illustrative_cost_micro_usd: int
    circuit_open: bool
    stop_reason: str | None
    limit_kind: str | None


class GuardError(Exception):
    """A limit was reached and the next unit of work was refused."""

    def __init__(self, kind: LimitKind, message: str, snapshot: GuardSnapshot):
        super().__init__(message)
        self.kind = kind
        self.snapshot = snapshot


class CircuitOpenError(GuardError):
    """The breaker is already open. No further work is admitted."""


class ReentryError(GuardError):
    """A second session tried to enter a guard that is already running."""


Clock = Callable[[], float]


def _default_clock() -> float:
    # Imported lazily so tests can avoid depending on a moving clock unless
    # they use the default. ``time.monotonic`` is the production clock.
    import time

    return time.monotonic()


class RuntimeGuard:
    """Session budget checked before each request, iteration, model call, and tool call."""

    def __init__(
        self,
        policy: GuardPolicy | None = None,
        ceilings: SafetyCeilings | None = None,
        rates: IllustrativeRates | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.ceilings = ceilings or DEFAULT_CEILINGS
        self.rates = rates or DEFAULT_RATES
        requested = policy or GuardPolicy(**self.ceilings.as_limits())  # type: ignore[arg-type]
        self.requested_policy = requested
        self.policy, self.clamp_warnings = clamp_policy(requested, self.ceilings)
        self._clock = clock or _default_clock
        self.reset()

    def reset(self) -> None:
        if getattr(self, "_active", False):
            raise RuntimeError("Cannot reset a guard while a session is active.")
        self._active = False
        self._tripped = False
        self._stop_kind: LimitKind | None = None
        self._stop_message: str | None = None
        self._origin: float | None = None
        self._finished: float | None = None
        self.iterations = 0
        self.requests_started = 0
        self.requests_completed = 0
        self.model_calls = 0
        self.tool_calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.max_context_tokens = 0
        self.stalled_iterations = 0
        self.call_log: list[tuple[int, int]] = []
        self._seen_results: set[str] = set()
        self._tools_this_iteration = 0
        self._new_this_iteration = 0
        self.events: list[str] = []
        self.warnings: list[str] = list(self.clamp_warnings)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def tripped(self) -> bool:
        return self._tripped

    @property
    def active(self) -> bool:
        return self._active

    @property
    def stop_reason(self) -> str | None:
        return self._stop_message

    @property
    def limit_kind(self) -> LimitKind | None:
        return self._stop_kind

    def elapsed_seconds(self) -> float:
        if self._origin is None:
            return 0.0
        end = self._clock() if self._active else (self._finished or self._clock())
        return max(0.0, end - self._origin)

    def cost_micro(self) -> int:
        return cost_micro_usd(
            self.input_tokens, self.output_tokens, self.tool_calls, self.rates
        )

    def snapshot(self) -> GuardSnapshot:
        return GuardSnapshot(
            iterations=self.iterations,
            requests_started=self.requests_started,
            model_calls=self.model_calls,
            tool_calls=self.tool_calls,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            total_tokens=self.total_tokens,
            max_context_tokens=self.max_context_tokens,
            elapsed_seconds=self.elapsed_seconds(),
            illustrative_cost_micro_usd=self.cost_micro(),
            circuit_open=self._tripped,
            stop_reason=self._stop_message,
            limit_kind=None if self._stop_kind is None else self._stop_kind.value,
        )

    @contextmanager
    def session(self) -> Iterator[RuntimeGuard]:
        self.begin()
        try:
            yield self
        finally:
            self.end()

    def begin(self) -> None:
        if self._active:
            message = (
                "This guard is already running a session. Nested or overlapping "
                "execution is refused."
            )
            raise ReentryError(LimitKind.REENTRY, message, self.snapshot())
        if self._tripped:
            raise CircuitOpenError(
                self._stop_kind or LimitKind.CIRCUIT,
                "Circuit breaker is open. "
                + (self._stop_message or "Reset the guard before another session."),
                self.snapshot(),
            )
        self._active = True
        self._origin = self._clock()
        self._finished = None
        self._note("session opened")

    def end(self) -> None:
        if self._origin is not None:
            self._finished = self._clock()
        self._active = False

    def before_request(self) -> None:
        self._prepare("request")
        self._check_budget(
            LimitKind.REQUESTS,
            measured=self.requests_started,
            policy_limit=self.policy.max_requests,
            ceiling_limit=self.ceilings.max_requests,
            unit="requests already started",
        )
        self.requests_started += 1
        self._note(f"request {self.requests_started} admitted")

    def before_iteration(self) -> None:
        self._prepare("iteration")
        self._check_budget(
            LimitKind.ITERATIONS,
            measured=self.iterations,
            policy_limit=self.policy.max_iterations,
            ceiling_limit=self.ceilings.max_iterations,
            unit="iterations already completed",
        )
        if self.stalled_iterations >= self.policy.max_stalled_iterations:
            self._trip(
                LimitKind.NO_PROGRESS,
                measured=self.stalled_iterations,
                policy_limit=self.policy.max_stalled_iterations,
                ceiling_limit=self.ceilings.max_stalled_iterations,
                unit="iterations in a row whose tool results were all repeats",
            )
        self._note(f"iteration {self.iterations + 1} admitted")

    def before_model(self, input_tokens: int, max_new_tokens: int) -> None:
        """Reserve the model call. Raises before any generation happens."""

        self._prepare("model call")
        self._check_count(input_tokens, "input_tokens")
        self._check_count(max_new_tokens, "max_new_tokens")
        context_limit = min(
            self.policy.max_context_tokens, self.ceilings.max_context_tokens
        )
        if input_tokens > context_limit:
            self._trip(
                LimitKind.CONTEXT,
                measured=input_tokens,
                policy_limit=self.policy.max_context_tokens,
                ceiling_limit=self.ceilings.max_context_tokens,
                unit="prompt tokens",
            )
        if input_tokens + max_new_tokens > context_limit:
            self._trip(
                LimitKind.CONTEXT,
                measured=input_tokens + max_new_tokens,
                policy_limit=self.policy.max_context_tokens,
                ceiling_limit=self.ceilings.max_context_tokens,
                unit="projected context tokens after the model call",
            )
        output_limit = min(
            self.policy.max_output_tokens_per_step,
            self.ceilings.max_output_tokens_per_step,
        )
        if max_new_tokens > output_limit:
            self._trip(
                LimitKind.TOKENS,
                measured=max_new_tokens,
                policy_limit=self.policy.max_output_tokens_per_step,
                ceiling_limit=self.ceilings.max_output_tokens_per_step,
                unit="reserved output tokens for one call",
            )
        projected_tokens = self.total_tokens + input_tokens + max_new_tokens
        token_limit = min(
            self.policy.max_total_tokens, self.ceilings.max_total_tokens
        )
        if projected_tokens > token_limit:
            self._trip(
                LimitKind.TOKENS,
                measured=projected_tokens,
                policy_limit=self.policy.max_total_tokens,
                ceiling_limit=self.ceilings.max_total_tokens,
                unit="projected total tokens if this call runs",
            )
        projected_cost = cost_micro_usd(
            self.input_tokens + input_tokens,
            self.output_tokens + max_new_tokens,
            self.tool_calls,
            self.rates,
        )
        policy_micro = _usd_to_micro(self.policy.max_estimated_cost_usd)
        ceiling_micro = _usd_to_micro(self.ceilings.max_estimated_cost_usd)
        if projected_cost > min(policy_micro, ceiling_micro):
            self._trip(
                LimitKind.COST,
                measured=projected_cost,
                policy_limit=policy_micro,
                ceiling_limit=ceiling_micro,
                unit="projected illustrative micro-USD if this call runs",
            )
        self._note(
            f"model call allowed (input {input_tokens}, reserved output {max_new_tokens})"
        )

    def before_tool_call(self) -> None:
        self._prepare("tool call")
        self._check_budget(
            LimitKind.TOOL_CALLS,
            measured=self.tool_calls,
            policy_limit=self.policy.max_tool_calls,
            ceiling_limit=self.ceilings.max_tool_calls,
            unit="tool calls already completed",
        )
        projected_cost = cost_micro_usd(
            self.input_tokens,
            self.output_tokens,
            self.tool_calls + 1,
            self.rates,
        )
        policy_micro = _usd_to_micro(self.policy.max_estimated_cost_usd)
        ceiling_micro = _usd_to_micro(self.ceilings.max_estimated_cost_usd)
        if projected_cost > min(policy_micro, ceiling_micro):
            self._trip(
                LimitKind.COST,
                measured=projected_cost,
                policy_limit=policy_micro,
                ceiling_limit=ceiling_micro,
                unit="projected illustrative micro-USD if this tool call runs",
            )
        self._note(f"tool call {self.tool_calls + 1} allowed")

    def before_context_growth(self, projected_context_tokens: int) -> None:
        """Refuse a tool whose result would push the transcript over the context limit."""

        self._prepare("context growth")
        self._check_count(projected_context_tokens, "projected_context_tokens")
        context_limit = min(
            self.policy.max_context_tokens, self.ceilings.max_context_tokens
        )
        if projected_context_tokens > context_limit:
            self._trip(
                LimitKind.CONTEXT,
                measured=projected_context_tokens,
                policy_limit=self.policy.max_context_tokens,
                ceiling_limit=self.ceilings.max_context_tokens,
                unit="projected context tokens",
            )

    def record_model(self, input_tokens: int, output_tokens: int) -> None:
        self._require_session()
        self._check_count(input_tokens, "input_tokens")
        self._check_count(output_tokens, "output_tokens")
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.model_calls += 1
        self.call_log.append((input_tokens, output_tokens))
        self.observe_context(input_tokens + output_tokens)
        if self.total_tokens > self.policy.max_total_tokens:
            self._trip(
                LimitKind.TOKENS,
                measured=self.total_tokens,
                policy_limit=self.policy.max_total_tokens,
                ceiling_limit=self.ceilings.max_total_tokens,
                unit="total tokens after the model call",
            )

    def record_iteration(self) -> None:
        self._require_session()
        self.iterations += 1
        self._note(f"iteration {self.iterations} completed")

    def record_tool_call(self, name: str, content: str = "") -> None:
        """Count a completed tool call and note whether its result was new.

        The guard keeps a short hash of each result, not the text itself.
        """

        self._require_session()
        if not isinstance(content, str):
            raise TypeError("content must be a string.")
        self.tool_calls += 1
        self._tools_this_iteration += 1
        fingerprint = hashlib.sha256(f"{name}\0{content}".encode("utf-8")).hexdigest()[:16]
        if fingerprint not in self._seen_results:
            self._seen_results.add(fingerprint)
            self._new_this_iteration += 1
        self._note(f"tool {name} completed (call {self.tool_calls})")
        projected = cost_micro_usd(
            self.input_tokens, self.output_tokens, self.tool_calls, self.rates
        )
        policy_micro = _usd_to_micro(self.policy.max_estimated_cost_usd)
        if projected > policy_micro or self.tool_calls > self.policy.max_tool_calls:
            kind = (
                LimitKind.TOOL_CALLS
                if self.tool_calls > self.policy.max_tool_calls
                else LimitKind.COST
            )
            measured = (
                self.tool_calls if kind is LimitKind.TOOL_CALLS else projected
            )
            policy_limit = (
                self.policy.max_tool_calls
                if kind is LimitKind.TOOL_CALLS
                else policy_micro
            )
            ceiling_limit = (
                self.ceilings.max_tool_calls
                if kind is LimitKind.TOOL_CALLS
                else _usd_to_micro(self.ceilings.max_estimated_cost_usd)
            )
            self._trip(
                kind,
                measured=measured,
                policy_limit=policy_limit,
                ceiling_limit=ceiling_limit,
                unit="usage after the tool call",
            )

    def end_iteration(self) -> None:
        """Close an iteration for the progress check.

        An iteration that called tools and got back only results the session has
        already seen counts as stalled. An iteration with no tool calls does not
        change the count.
        """

        self._require_session()
        if self._tools_this_iteration:
            if self._new_this_iteration:
                self.stalled_iterations = 0
            else:
                self.stalled_iterations += 1
                self._note(
                    f"iteration {self.iterations} fetched nothing new "
                    f"({self.stalled_iterations} in a row)"
                )
        self._tools_this_iteration = 0
        self._new_this_iteration = 0

    def record_request_completed(self) -> None:
        self._require_session()
        self.requests_completed += 1

    def observe_context(self, tokens: int) -> None:
        self._check_count(tokens, "context tokens")
        if tokens > self.max_context_tokens:
            self.max_context_tokens = tokens

    def annotate(self, message: str) -> None:
        if not isinstance(message, str) or not message.strip():
            raise ValueError("annotation must be a non-empty string.")
        self._note(message.strip())

    def current_cost(self) -> object:
        return estimate_cost(
            self.input_tokens, self.output_tokens, self.tool_calls, self.rates
        )

    def _prepare(self, action: str) -> None:
        self._require_session()
        elapsed = self.elapsed_seconds()
        limit = min(self.policy.max_execution_seconds, self.ceilings.max_execution_seconds)
        if elapsed >= limit:
            self._trip(
                LimitKind.TIME,
                measured=elapsed,
                policy_limit=self.policy.max_execution_seconds,
                ceiling_limit=self.ceilings.max_execution_seconds,
                unit=f"seconds elapsed before the next {action}",
            )
        spent = self.cost_micro()
        policy_micro = _usd_to_micro(self.policy.max_estimated_cost_usd)
        ceiling_micro = _usd_to_micro(self.ceilings.max_estimated_cost_usd)
        if spent > min(policy_micro, ceiling_micro):
            self._trip(
                LimitKind.COST,
                measured=spent,
                policy_limit=policy_micro,
                ceiling_limit=ceiling_micro,
                unit=f"illustrative micro-USD already spent before the next {action}",
            )

    def _require_session(self) -> None:
        if not self._active:
            raise RuntimeError(
                "Runtime guard checks only run inside an active session."
            )
        if self._tripped:
            raise CircuitOpenError(
                self._stop_kind or LimitKind.CIRCUIT,
                "Circuit breaker is open. " + (self._stop_message or ""),
                self.snapshot(),
            )

    def _check_budget(
        self,
        kind: LimitKind,
        *,
        measured: int,
        policy_limit: int,
        ceiling_limit: int,
        unit: str,
    ) -> None:
        if measured >= policy_limit or measured >= ceiling_limit:
            self._trip(
                kind,
                measured=measured,
                policy_limit=policy_limit,
                ceiling_limit=ceiling_limit,
                unit=unit,
            )

    def _trip(
        self,
        kind: LimitKind,
        *,
        measured: object,
        policy_limit: object,
        ceiling_limit: object,
        unit: str,
    ) -> None:
        self._tripped = True
        self._stop_kind = kind
        message = (
            "Runtime guard stopped execution before the next unit of work. "
            f"Limit reached: {kind.value}. "
            f"Measured {measured} {unit}. "
            f"Policy limit {policy_limit}. "
            f"Hard safety ceiling {ceiling_limit}. "
            "No further model calls or tool calls will run until the guard is reset. "
            f"{COST_DISCLAIMER}"
        )
        if kind is LimitKind.COST:
            message = (
                "Runtime guard stopped execution before the next unit of work. "
                f"Limit reached: cost. "
                f"Projected or spent illustrative amount {format_usd_micro(int(measured))} USD. "
                f"Policy limit {format_usd_micro(int(policy_limit))} USD. "
                f"Hard safety ceiling {format_usd_micro(int(ceiling_limit))} USD. "
                "No further model calls or tool calls will run until the guard is reset. "
                f"{COST_DISCLAIMER}"
            )
        self._stop_message = message
        self._note(message)
        raise GuardError(kind, message, self.snapshot())

    def _note(self, message: str) -> None:
        if len(self.events) < 1000:
            self.events.append(message)

    @staticmethod
    def _check_count(value: int, name: str) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer.")


def _usd_to_micro(usd: object) -> int:
    from decimal import Decimal, ROUND_HALF_UP

    micro = Decimal(str(usd)) * Decimal(1_000_000)
    return int(micro.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
