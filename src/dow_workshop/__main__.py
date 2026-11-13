"""Print the workshop scenarios. No model download and no network calls."""

from __future__ import annotations

from dow_workshop.attack_simulator import (
    amplification_note,
    compare_scenarios,
    format_growth_table,
    format_report,
)
from dow_workshop.challenge import format_challenge, score_policy
from dow_workshop.config import (
    BUDGET_POLICY,
    COST_DISCLAIMER,
    PROJECT_SUBTITLE,
    format_boundary,
    PROJECT_TITLE,
)

# The policy that wins round one: the progress check and a tool budget that
# fits the longest visible task exactly.
VISIBLE_WINNER = {"max_stalled_iterations": 1, "max_tool_calls": 8}


def main() -> None:
    print(PROJECT_TITLE)
    print(PROJECT_SUBTITLE)
    print("Status: beta. These materials are still in development.")
    print()
    results = compare_scenarios()
    print(format_report(results))
    print()
    normal, poisoned = results[0], results[1]
    print(amplification_note(normal, poisoned))
    print()
    print("Prompt size at each model call (poisoned note, no policy):")
    print(", ".join(f"{size:,}" for size in poisoned.prompt_sizes))
    print()
    print(format_growth_table())
    print()
    print("Transcript, poisoned note under the progress check (last lines):")
    print("\n".join(results[4].transcript[-5:]))
    print()
    print("Challenge starting point: the budget policy.")
    print(format_challenge(score_policy(BUDGET_POLICY)))
    print()
    print("The policy that wins round one, scored on all six tests.")
    print(format_challenge(score_policy(VISIBLE_WINNER, held_out=True)))
    print()
    print(format_boundary())
    print()
    print(COST_DISCLAIMER)


if __name__ == "__main__":
    main()
