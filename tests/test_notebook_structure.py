"""The Colab notebook contains the workshop contract and runs end to end."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "notebooks" / "denial_of_wallet_workshop.ipynb"


def _cells() -> list[dict]:
    return json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]


def _text(cell: dict) -> str:
    source = cell["source"]
    return "".join(source) if isinstance(source, list) else source


def _source() -> str:
    return "\n".join(_text(cell) for cell in _cells())


def _code_cells() -> list[str]:
    return [_text(cell) for cell in _cells() if cell["cell_type"] == "code"]


def test_notebook_has_the_required_sections() -> None:
    source = _source()
    for heading in (
        "RUN CONTROLLED AMPLIFICATION EXPERIMENT",
        "ACTIVATE RUNTIME PROTECTION",
        "ILLUSTRATIVE SIMULATED COST. NOT AN ACTUAL API BILL.",
        "Which metric surprised you most?",
        "Could traditional request-rate monitoring have detected this?",
        "Which safeguards were most effective?",
        "What would you monitor in a production environment?",
        "Keep searching until you are sure",
        "What is mocked and what is real",
        "What this notebook is evidence of",
        "Optional: put a real model in the loop",
        "This stand-in is not a model.",
        "commit to a guess",
        "Challenge, round one: stop the attacks, let the real work finish",
        "Look inside one test",
        "Round two: what the attacker does next",
        "What round two is for",
        "Your own agent",
        "build_notebook.py",
        "docs/worksheet.md",
    ):
        assert heading in source


def test_notebook_is_in_sync_with_its_builder(tmp_path) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("build_notebook", ROOT / "notebooks" / "build_notebook.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    expected = [(cell["source"], cell["metadata"]) for cell in module.CELLS]
    assert [(cell["source"], cell["metadata"]) for cell in _cells()] == expected, (
        "Rebuild the notebook: python notebooks/build_notebook.py"
    )


def test_only_the_setup_cell_hides_its_code() -> None:
    hidden = [_text(cell) for cell in _cells() if cell["metadata"].get("cellView") == "form"]
    assert len(hidden) == 1
    assert hidden[0].startswith("# @title Setup")


def test_notebook_does_not_ask_for_an_api_key() -> None:
    source = _source().lower()
    for banned in ("api_key", "openai", "anthropic", "sk-", "from_pretrained", "pip install"):
        assert banned not in source


def test_notebook_has_no_outputs_committed() -> None:
    for cell in _cells():
        if cell["cell_type"] == "code":
            assert cell["outputs"] == []


def _isolate_package(monkeypatch):
    saved_path = list(sys.path)
    saved_modules = {
        name: sys.modules[name]
        for name in list(sys.modules)
        if name == "dow_workshop" or name.startswith("dow_workshop.")
    }
    for name in saved_modules:
        del sys.modules[name]
    sys.path[:] = [
        entry
        for entry in sys.path
        if not entry.endswith(f"{os.sep}src") and "dow_workshop" not in entry
    ]

    def restore() -> None:
        sys.path[:] = saved_path
        for name in list(sys.modules):
            if name == "dow_workshop" or name.startswith("dow_workshop."):
                del sys.modules[name]
        sys.modules.update(saved_modules)

    return restore


@pytest.mark.filterwarnings("ignore:FigureCanvasAgg is non-interactive")
def test_uploaded_notebook_runs_end_to_end_twice(tmp_path, monkeypatch) -> None:
    """A Colab upload has only the ipynb. Every cell must run, and re-run, from it."""

    pytest.importorskip("matplotlib")
    monkeypatch.setenv("MPLBACKEND", "Agg")
    monkeypatch.chdir(tmp_path)
    restore = _isolate_package(monkeypatch)
    try:
        namespace: dict[str, object] = {"__name__": "__main__"}
        cells = _code_cells()
        for _round in range(2):
            for index, cell in enumerate(cells):
                exec(compile(cell, f"cell-{index}", "exec"), namespace)
        loaded = sys.modules["dow_workshop"].__file__
        assert loaded is not None
        assert Path(loaded).is_relative_to(tmp_path)
        assert namespace["poisoned"].metrics.total_tokens == 18_560
        assert namespace["challenge"].legit_finished == 0
        assert len(namespace["scoreboard"].attempts) == 1
        assert len(namespace["round_two"].rows) == 6
        assert namespace["my_exposure"].hijacked.total_tokens == 18_560
        # The optional real-model sketch runs offline on its stand-in.
        assert namespace["real_clean"].model_calls == 2
        assert namespace["real_poisoned"].model_calls == 10
        assert namespace["real_guarded"].limit_kind.value == "no_progress"
        assert namespace["real_guarded"].model_calls < namespace["real_poisoned"].model_calls
        import matplotlib.pyplot as plt

        plt.close("all")
    finally:
        restore()
