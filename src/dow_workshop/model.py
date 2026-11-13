"""A deterministic language-model stand-in.

The workshop does not load model weights and does not call a model API.
The stand-in follows a published token rule so every machine prints the same
counts. What the agent decides is scripted in ``agent.py`` and ``planner.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

from dow_workshop.config import DEFAULT_CEILINGS
from dow_workshop.metrics import estimate_tokens, text_with_token_count


@dataclass(frozen=True)
class ModelOutput:
    text: str
    input_tokens: int
    output_tokens: int


class DeterministicModel:
    """Instant stand-in with the workshop token rules.

    Output length is exactly the requested ``max_new_tokens``, capped by the
    hard per-step ceiling. Given the same prompt size, the token counts do
    not change between machines.
    """

    name = "deterministic-simulation"

    def count_tokens(self, text: str) -> int:
        return estimate_tokens(text)

    def render(self, target_tokens: int, prefix: str) -> str:
        return text_with_token_count(target_tokens, prefix)

    def generate(self, prompt: str, max_new_tokens: int) -> ModelOutput:
        if isinstance(max_new_tokens, bool) or not isinstance(max_new_tokens, int):
            raise ValueError("max_new_tokens must be an integer.")
        ceiling = DEFAULT_CEILINGS.max_output_tokens_per_step
        if max_new_tokens < 1 or max_new_tokens > ceiling:
            raise ValueError(
                f"max_new_tokens must be between 1 and the hard ceiling {ceiling}."
            )
        if not isinstance(prompt, str):
            raise TypeError("prompt must be a string.")
        text = text_with_token_count(max_new_tokens, "Checked the local note.")
        return ModelOutput(
            text=text,
            input_tokens=estimate_tokens(prompt),
            output_tokens=estimate_tokens(text),
        )
