"""Charts for the notebook. Optional: the workshop runs without matplotlib.

matplotlib is imported inside each function, so importing the package never
needs it. One colour per meaning throughout: blue is attack-driven tokens,
teal is legitimate work, grey is the same run with no policy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from dow_workshop.attack_simulator import ExperimentResult
    from dow_workshop.challenge import ChallengeResult

INK = "#141A24"
SECONDARY = "#4B5768"
RULE = "#C4C6C8"
DIVIDER = "#DFE2E6"
SURFACE = "#F6F8FB"
ATTACK = "#3F5DAE"
LEGIT = "#24877B"


def have_matplotlib() -> bool:
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        return False
    return True


def _pyplot():
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    installed = {font.name for font in font_manager.fontManager.ttflist}
    family = [name for name in ("IBM Plex Sans", "DejaVu Sans") if name in installed]
    plt.rcParams.update(
        {
            "font.family": family or ["sans-serif"],
            "text.color": INK,
            "axes.edgecolor": RULE,
            "axes.labelcolor": SECONDARY,
            "xtick.color": SECONDARY,
            "ytick.color": INK,
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
        }
    )
    return plt


def _heading(figure, axis, text: str) -> None:
    """A heading that starts at the left edge of the figure, above one axis."""

    from matplotlib import transforms

    axis.set_title(" ", fontsize=12, pad=10)
    axis.text(
        0.015,
        1.0,
        text,
        transform=transforms.blended_transform_factory(figure.transFigure, axis.transAxes),
        fontsize=12,
        va="bottom",
        ha="left",
    )


def _bare(axis, *, keep: Sequence[str] = ("bottom",)) -> None:
    for side in ("top", "right", "left", "bottom"):
        axis.spines[side].set_visible(side in keep)
    axis.tick_params(length=0)


def draw_staircase(result: "ExperimentResult"):
    """One bar per model call. Height is what that call re-read."""

    plt = _pyplot()
    sizes = list(result.prompt_sizes)
    if not sizes:
        raise ValueError("The run made no model calls, so there is nothing to draw.")
    calls = list(range(1, len(sizes) + 1))
    colours = [LEGIT] + [ATTACK] * (len(sizes) - 1)
    figure, axis = plt.subplots(figsize=(10, 4.4))
    axis.bar(calls, sizes, color=colours, width=0.72)
    peak = max(sizes)
    for call, size in zip(calls, sizes):
        axis.text(call, size + peak * 0.02, f"{size:,}", ha="center", va="bottom", fontsize=9.5)
    axis.set_xticks(calls)
    axis.set_xticklabels([f"call {call}" for call in calls])
    axis.set_yticks([])
    axis.set_ylim(0, peak * 1.3)
    _bare(axis)
    total = sum(sizes)
    axis.set_title(
        f"Each model call re-reads everything before it. Added together: {total:,} input tokens.",
        loc="left",
        fontsize=12.5,
        pad=14,
    )
    axis.text(
        0.0,
        0.95,
        "Tokens the model reads at each call",
        transform=axis.transAxes,
        color=SECONDARY,
        fontsize=10,
        va="top",
    )
    if len(sizes) > 1:
        axis.annotate(
            "A normal request\nstops here",
            xy=(1, sizes[0] + peak * 0.1),
            xytext=(1, peak * 0.42),
            ha="center",
            color=LEGIT,
            fontsize=10,
            arrowprops={"arrowstyle": "-", "color": LEGIT, "linewidth": 1},
        )
        axis.text(
            len(sizes) / 2 + 1,
            peak * 0.82,
            "Everything in blue is the note's doing",
            ha="center",
            color=ATTACK,
            fontsize=10,
        )
    figure.tight_layout()
    return figure


def _outcome(item: "ExperimentResult") -> str:
    m = item.metrics
    if item.notes == "clean":
        if m.answer_status == "complete":
            return "finished"
        return f"cut short by {(m.limit_kind or m.stopped_by).replace('_', ' ')}"
    if m.limit_kind:
        return f"stopped by {m.limit_kind.replace('_', ' ')}"
    return "ran to the iteration limit"


def draw_comparison(results: Sequence["ExperimentResult"]):
    """Total tokens for each workshop row. Every row is one request."""

    plt = _pyplot()
    from matplotlib.patches import Patch

    rows = list(reversed(list(results)))
    values = [item.metrics.total_tokens for item in rows]
    colours = [LEGIT if item.notes == "clean" else ATTACK for item in rows]
    figure, axis = plt.subplots(figsize=(10, 4.2))
    bars = axis.barh([item.scenario for item in rows], values, color=colours, height=0.55)
    peak = max(values)
    for bar, item in zip(bars, rows):
        axis.text(
            bar.get_width() + peak * 0.012,
            bar.get_y() + bar.get_height() / 2,
            f"{item.metrics.total_tokens:,}  {_outcome(item)}",
            va="center",
            fontsize=10,
        )
    axis.set_xlim(0, peak * 1.4)
    axis.set_xticks([])
    _bare(axis, keep=())
    _heading(figure, axis, "Every row is one request. Only the notes and the policy change.")
    axis.legend(
        handles=[
            Patch(color=ATTACK, label="Tokens when the note is tampered"),
            Patch(color=LEGIT, label="Tokens for legitimate work"),
        ],
        loc="lower right",
        frameon=False,
    )
    figure.tight_layout()
    return figure


def draw_challenge(result: "ChallengeResult"):
    """Real work as notes read, attacks as tokens let through."""

    plt = _pyplot()
    legit = [row for row in result.rows if row.test.kind == "legit"]
    attacks = [row for row in result.rows if row.test.kind == "attack"]
    height = 1.5 + 0.55 * len(result.rows)
    figure, (top, bottom) = plt.subplots(
        2,
        1,
        figsize=(10, height),
        gridspec_kw={"height_ratios": [len(legit) + 0.6, len(attacks) + 0.6]},
    )

    widest = max(row.reads_planned for row in legit)
    for position, row in enumerate(legit):
        y = len(legit) - 1 - position
        done = row.reads_done
        top.scatter(
            range(1, done + 1), [y] * done, marker="D", s=95, color=LEGIT, zorder=3
        )
        missing = range(done + 1, row.reads_planned + 1)
        top.scatter(
            list(missing),
            [y] * len(missing),
            marker="D",
            s=95,
            facecolors="none",
            edgecolors=RULE,
            linewidths=1.4,
            zorder=3,
        )
        verdict = (
            "finished"
            if row.passed
            else f"cut short at {done} of {row.reads_planned} ({row.stopped_by_knob})"
        )
        top.text(
            row.reads_planned + 0.7,
            y,
            verdict,
            va="center",
            fontsize=10,
            color=LEGIT if row.passed else INK,
            fontweight="normal" if row.passed else "bold",
        )
    top.set_yticks(range(len(legit)))
    top.set_yticklabels([f"{row.number}. {row.test.name}" for row in reversed(legit)])
    top.set_xlim(0.3, widest * 2.7)
    top.set_ylim(-0.6, len(legit) - 0.4)
    top.set_xticks([])
    _bare(top, keep=())
    _heading(
        figure,
        top,
        f"Real work finished: {result.legit_finished} of {result.legit_total} tasks. "
        "Each diamond is one read the task needed.",
    )

    peak = max(row.baseline_tokens for row in attacks)
    for position, row in enumerate(attacks):
        y = len(attacks) - 1 - position
        tokens = row.result.metrics.total_tokens
        bottom.barh(y, row.baseline_tokens, color=DIVIDER, height=0.5, zorder=2)
        bottom.barh(y, tokens, color=ATTACK, height=0.5, zorder=3)
        verdict = (
            f"{tokens:,} got through ({row.stopped_by_knob})"
            if row.passed
            else f"{tokens:,} got through (nothing stopped it)"
        )
        bottom.text(
            row.baseline_tokens + peak * 0.012,
            y,
            verdict,
            va="center",
            fontsize=10,
            fontweight="normal" if row.passed else "bold",
        )
    bottom.set_yticks(range(len(attacks)))
    bottom.set_yticklabels([f"{row.number}. {row.test.name}" for row in reversed(attacks)])
    bottom.set_xlim(0, peak * 2.5)
    bottom.set_ylim(-0.6, len(attacks) - 0.4)
    bottom.set_xticks([])
    _bare(bottom, keep=())
    _heading(
        figure,
        bottom,
        f"Attack tokens let through: {result.attack_tokens:,} of "
        f"{result.baseline_attack_tokens:,}. Grey is the same attack with no policy.",
    )
    figure.tight_layout(h_pad=1.6)
    return figure
