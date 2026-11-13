"""House style that is cheap to break by accident."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = {".venv", ".git", "__pycache__", ".pytest_cache", "_dow_embedded"}
SUFFIXES = {".py", ".md", ".html", ".mmd", ".toml", ".ipynb", ".txt"}
DASH = chr(0x2014)
# json.dumps writes the character as a backslash escape inside the notebook.
ESCAPED = chr(92) + "u2014"


def _files() -> list[Path]:
    return [
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and path.suffix in SUFFIXES
        and not any(part in SKIP or part.endswith(".egg-info") for part in path.parts)
    ]


def test_no_em_dashes() -> None:
    offenders = []
    for path in [*_files(), ROOT / "LICENSE"]:
        text = path.read_text(encoding="utf-8")
        if DASH in text or ESCAPED in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], f"Recast these sentences without an em-dash: {offenders}"
