"""Defaults, the illustrative rate card, and non-bypassable safety ceilings.

Notebook parameters and guard policies are clamped to these ceilings.
Nothing in the workshop UI can raise them.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Mapping


COST_DISCLAIMER = "ILLUSTRATIVE SIMULATED COST. NOT AN ACTUAL API BILL."

PROJECT_TITLE = "Cost as an Attack Surface"
PROJECT_SUBTITLE = (
    "Understanding and Defending Against Denial-of-Wallet Attacks in Agentic AI"
)
PROJECT_URL = "https://github.com/prismatic-labs/cost-as-an-attack-surface"

# Each user request starts from a short local prompt of this many estimated tokens.
# Tool text is not billed as model input until a later model call reads it back.
INITIAL_CONTEXT_TOKENS = 64
# Every note and every search result is this many estimated tokens long.
NOTE_TOKENS = 160
# Output reserved for each model call.
OUTPUT_TOKENS = 64
# The agent's own per-request iteration limit, the kind of default agent frameworks
# ship. It is not a budget: an attacker who triggers the loop gets all of it.
AGENT_MAX_STEPS = 10
DEFAULT_NOTE = "DOC-14"
# Appendix pages in the ``bulky`` note set are this long. It equals the hard
# ceiling on tool text per call, so the sandbox cannot serve a larger page.
LARGE_PAGE_TOKENS = 512

# The user's request is benign in every attack scenario.
DEFAULT_TASK = "Summarise the operations note DOC-14 and name one follow-up check."
# A legitimate task that needs several steps.
LONG_TASK = "Compare the operations notes DOC-11 to DOC-14 and list where they disagree."
# The same legitimate task, twice as long. The third visible test in the challenge.
LONGER_TASK = "Compare the operations notes DOC-11 to DOC-18 and list where they disagree."
# A legitimate task that goes back over two notes it has already read. Real
# agents do this. It is what gives a strict progress check a false positive.
RECHECK_TASK = (
    "Compare the operations notes DOC-11 to DOC-18, then re-read DOC-15 and "
    "DOC-16 to confirm where they disagree."
)
# A user who is allowed to ask for exhaustive work can trigger the loop directly.
KEEP_GOING_TASK = "Summarise DOC-14. Keep searching until you are sure."

OPERATIONAL_LIMITATIONS: tuple[str, ...] = (
    "Google Colab free compute is not guaranteed and follows Google's own limits.",
    "The agent is scripted so every machine prints the same numbers.",
    "Hard safety ceilings in this repository cannot be raised from the notebook.",
    "Illustrative costs use a synthetic rate card and are not an API invoice.",
    "Nothing in the package opens a network connection.",
)

# What is mocked and what is real, in one place. The notebook, the CLI, the
# README and the slides all print this, and a test keeps them in step.
SIMULATION_BOUNDARY: tuple[tuple[str, str, str], ...] = (
    (
        "The model",
        "mocked",
        "No LLM runs. It emits fixed-length filler, and tokens are counted as "
        "one per four characters.",
    ),
    (
        "The agent's decisions",
        "mocked",
        'Scripted. It obeys a short list of "keep going" phrasings.',
    ),
    (
        "The tools and notes",
        "mocked",
        "They return local fictional text of a fixed size.",
    ),
    ("The prices", "mocked", "A teaching rate card, not a vendor's."),
    (
        "The guard",
        "real",
        "Real code. It makes each allow-or-refuse decision before each call, "
        "including the progress check and the circuit breaker.",
    ),
    (
        "The token growth",
        "real",
        "Exact arithmetic on estimated token counts. It follows from re-reading "
        "a growing transcript and holds for any agent that does that.",
    ),
    (
        "The scoring and the exposure calculator",
        "real",
        "Real computation, over the simulated runs and over the numbers you type.",
    ),
)
BOUNDARY_VERDICT = (
    "The notebook measures what a loop costs once it starts and which limit "
    "stops it, published research in presentation/references.md shows that "
    "real models can be made to start one, and the last cell of the notebook "
    "sketches how to check a model you run."
)


def format_boundary() -> str:
    """The mocked and the real parts of the workshop, as plain text."""

    width = max(len(part) for part, _status, _detail in SIMULATION_BOUNDARY)
    lines = ["What is mocked and what is real:"]
    for part, status, detail in SIMULATION_BOUNDARY:
        lines.append(f"  {status.upper():<6}  {part:<{width}}  {detail}")
    lines.append(BOUNDARY_VERDICT)
    return "\n".join(lines)


def _decimal(value: object, name: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{name} must be a non-negative number.")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be a non-negative number.") from exc
    if not number.is_finite() or number < 0:
        raise ValueError(f"{name} must be a non-negative finite number.")
    return number


def _count(value: object, name: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer.")
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}.")
    return value


def _seconds(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number of seconds.")
    seconds = float(value)
    if seconds < 0 or seconds > 3600:
        raise ValueError(f"{name} must be between 0 and 3600 seconds.")
    return seconds


@dataclass(frozen=True)
class SafetyCeilings:
    """Absolute sandbox limits. User configuration cannot raise these."""

    max_iterations: int = 24
    max_requests: int = 6
    max_tool_calls: int = 64
    max_total_tokens: int = 50_000
    max_context_tokens: int = 8_000
    max_output_tokens_per_step: int = 128
    max_context_pad_tokens: int = 512
    max_stalled_iterations: int = 24
    max_execution_seconds: float = 180.0
    max_estimated_cost_usd: Decimal = Decimal("5")

    def as_limits(self) -> dict[str, object]:
        return {
            "max_iterations": self.max_iterations,
            "max_requests": self.max_requests,
            "max_tool_calls": self.max_tool_calls,
            "max_total_tokens": self.max_total_tokens,
            "max_context_tokens": self.max_context_tokens,
            "max_output_tokens_per_step": self.max_output_tokens_per_step,
            "max_stalled_iterations": self.max_stalled_iterations,
            "max_execution_seconds": self.max_execution_seconds,
            "max_estimated_cost_usd": self.max_estimated_cost_usd,
        }


DEFAULT_CEILINGS = SafetyCeilings()


@dataclass(frozen=True)
class IllustrativeRates:
    """Synthetic teaching rates. Not a price list and not a cloud invoice.

    Round numbers shaped like hosted inference plus a paid search tool.

    Units:
    - input and output rates are USD per one million tokens
    - tool rate is USD per mock tool call
    """

    input_usd_per_million_tokens: Decimal = Decimal("3")
    output_usd_per_million_tokens: Decimal = Decimal("15")
    usd_per_tool_call: Decimal = Decimal("0.005")

    def __post_init__(self) -> None:
        input_rate = _decimal(
            self.input_usd_per_million_tokens, "input_usd_per_million_tokens"
        )
        output_rate = _decimal(
            self.output_usd_per_million_tokens, "output_usd_per_million_tokens"
        )
        tool_rate = _decimal(self.usd_per_tool_call, "usd_per_tool_call")
        if input_rate > 1000 or output_rate > 1000 or tool_rate > 10:
            raise ValueError(
                "Illustrative rates are outside the workshop's sanity bounds."
            )
        object.__setattr__(self, "input_usd_per_million_tokens", input_rate)
        object.__setattr__(self, "output_usd_per_million_tokens", output_rate)
        object.__setattr__(self, "usd_per_tool_call", tool_rate)


DEFAULT_RATES = IllustrativeRates()


@dataclass(frozen=True)
class GuardPolicy:
    """Configurable runtime budget. Always clamped to :class:`SafetyCeilings`.

    ``max_stalled_iterations`` is the progress check: the guard refuses the next
    iteration after this many iterations in a row whose tool results contained
    nothing the session had not already seen. At the ceiling it is effectively off.
    """

    max_iterations: int = 24
    max_requests: int = 6
    max_tool_calls: int = 64
    max_total_tokens: int = 50_000
    max_context_tokens: int = 8_000
    max_output_tokens_per_step: int = 128
    max_stalled_iterations: int = 24
    max_execution_seconds: float = 180.0
    max_estimated_cost_usd: Decimal = Decimal("5")

    def __post_init__(self) -> None:
        for field, minimum, maximum in (
            ("max_iterations", 0, 1_000_000),
            ("max_requests", 0, 1_000_000),
            ("max_tool_calls", 0, 1_000_000),
            ("max_total_tokens", 0, 10_000_000),
            ("max_context_tokens", 1, 1_000_000),
            ("max_output_tokens_per_step", 1, 100_000),
            ("max_stalled_iterations", 1, 1_000_000),
        ):
            value = _count(getattr(self, field), field, minimum=minimum, maximum=maximum)
            object.__setattr__(self, field, value)
        object.__setattr__(
            self,
            "max_execution_seconds",
            _seconds(self.max_execution_seconds, "max_execution_seconds"),
        )
        object.__setattr__(
            self,
            "max_estimated_cost_usd",
            _decimal(self.max_estimated_cost_usd, "max_estimated_cost_usd"),
        )

    def describe(self) -> str:
        return ", ".join(f"{field}={getattr(self, field)}" for field in POLICY_FIELDS)


POLICY_FIELDS = (
    "max_iterations",
    "max_requests",
    "max_tool_calls",
    "max_total_tokens",
    "max_context_tokens",
    "max_output_tokens_per_step",
    "max_stalled_iterations",
    "max_execution_seconds",
    "max_estimated_cost_usd",
)


def sandbox_policy(ceilings: SafetyCeilings | None = None) -> GuardPolicy:
    """Policy that sits exactly on the hard safety ceiling.

    This is the loosest policy the sandbox will run. It is not unlimited.
    """

    limits = (ceilings or DEFAULT_CEILINGS).as_limits()
    return GuardPolicy(**limits)  # type: ignore[arg-type]


# Defence one: a tight budget. It stops the poisoned loop after two model
# calls. It also stops a legitimate four-step task after two.
BUDGET_POLICY = GuardPolicy(
    max_iterations=2,
    max_requests=6,
    max_tool_calls=8,
    max_total_tokens=2_000,
    max_context_tokens=4_000,
    max_output_tokens_per_step=128,
    max_execution_seconds=30,
    max_estimated_cost_usd=Decimal("0.50"),
)

# Defence two: a progress check on top of the sandbox ceiling. One iteration
# that fetched nothing new is enough to refuse the next one.
PROGRESS_POLICY = GuardPolicy(
    **{
        **{field: getattr(sandbox_policy(), field) for field in POLICY_FIELDS},
        "max_stalled_iterations": 1,
    }  # type: ignore[arg-type]
)


def clamp_policy(
    policy: GuardPolicy, ceilings: SafetyCeilings | None = None
) -> tuple[GuardPolicy, tuple[str, ...]]:
    """Return a policy that cannot exceed the hard ceilings."""

    limits = (ceilings or DEFAULT_CEILINGS).as_limits()
    values: dict[str, object] = {}
    warnings: list[str] = []
    for field in POLICY_FIELDS:
        requested = getattr(policy, field)
        ceiling = limits[field]
        if requested > ceiling:
            warnings.append(
                f"{field} reduced from {requested} to the hard safety ceiling {ceiling}."
            )
            values[field] = ceiling
        else:
            values[field] = requested
    return GuardPolicy(**values), tuple(warnings)  # type: ignore[arg-type]


def policy_from_mapping(
    values: Mapping[str, object], ceilings: SafetyCeilings | None = None
) -> tuple[GuardPolicy, tuple[str, ...]]:
    """Build a policy from a notebook mapping and clamp it.

    Fields that are left out sit on the sandbox ceiling.
    """

    base = sandbox_policy(ceilings)
    merged = {field: getattr(base, field) for field in POLICY_FIELDS}
    unknown = sorted(set(values) - set(POLICY_FIELDS))
    if unknown:
        raise ValueError(f"Unknown policy fields: {', '.join(unknown)}.")
    merged.update(values)
    return clamp_policy(GuardPolicy(**merged), ceilings)  # type: ignore[arg-type]
