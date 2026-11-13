"""Numbers typed into the slides and docs must match what the code computes.

The deck is written by hand. These tests read it back and compare every
figure and every quoted output with the tested simulation, so a slide
cannot drift. They also check that the PDF was built from the current deck.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from dow_workshop.attack_simulator import (
    HIJACKED_WORKLOAD,
    NORMAL_WORKLOAD,
    compare_scenarios,
    growth_table,
    project_workload,
    run_session,
)
from dow_workshop.challenge import reference_rows, score_policy
from dow_workshop.config import (
    BOUNDARY_VERDICT,
    BUDGET_POLICY,
    SIMULATION_BOUNDARY,
    format_boundary,
)
from dow_workshop.exposure import estimate_exposure
from dow_workshop.metrics import format_usd

ROOT = Path(__file__).resolve().parents[1]
DECK = "presentation/deck.html"
SLIDE_COUNT = 25
ROUND_ONE_WINNER = {"max_stalled_iterations": 1, "max_tool_calls": 8}
# The example on the "your own agent" slide.
EXAMPLE_AGENT = {
    "iteration_limit": 25,
    "first_prompt_tokens": 2_000,
    "tool_text_tokens_per_step": 3_000,
    "output_tokens_per_call": 400,
    "tool_calls_per_step": 2,
    "requests_per_day": 500,
    "context_window_tokens": 200_000,
}


def _strip(html: str) -> list[str]:
    """Text lines with HTML tags removed and entities decoded."""

    html = html.replace("</tr>", "\n")
    text = re.sub(r"<[^>]+>", " ", html)
    for entity, char in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">")):
        text = text.replace(entity, char)
    return [" ".join(line.split()) for line in text.splitlines()]


def _plain(path: str) -> list[str]:
    return _strip((ROOT / path).read_text(encoding="utf-8"))


def _slide(title_part: str) -> list[str]:
    """The text lines of the one slide whose title contains ``title_part``."""

    html = (ROOT / DECK).read_text(encoding="utf-8")
    slides = [part for part in html.split('<section class="slide')[1:]]
    found = [part.split("</section>")[0] for part in slides if title_part in part.split("</h1>")[0]]
    assert len(found) == 1, f"{len(found)} slides have a title containing {title_part!r}"
    return _strip(found[0])


def _line_with(lines: list[str], *parts: str) -> str:
    for line in lines:
        if all(part in line for part in parts):
            return line
    raise AssertionError(f"No line contains all of {parts}")


def test_the_deck_has_the_expected_number_of_slides() -> None:
    html = (ROOT / DECK).read_text(encoding="utf-8")
    assert html.count('<section class="slide') == SLIDE_COUNT
    assert f'<span id="count">{SLIDE_COUNT}</span>' in html


def test_the_deck_is_one_self_contained_file() -> None:
    """It is opened from a laptop and screen-shared, so it cannot depend on local files."""

    html = (ROOT / DECK).read_text(encoding="utf-8")
    for image in re.findall(r"<img [^>]*>", html):
        assert 'src="data:image/png;base64,' in image, image[:60]
    for source in re.findall(r'(?:src|href)="([^"]+)"', html):
        assert source.startswith(("https://", "mailto:", "#", "data:image/png;base64,")), source[:60]


def test_growth_table_on_the_slide_matches_the_code() -> None:
    lines = _plain(DECK)
    normal = project_workload(NORMAL_WORKLOAD)
    row = _line_with(lines, "1 step (normal)")
    assert f"{normal.total_tokens:,}" in row
    assert format_usd(normal.cost_micro_usd, 4) in row
    for projection in growth_table():
        row = _line_with(lines, f"{projection.iterations} steps", f"{projection.total_tokens:,}")
        assert format_usd(projection.cost_micro_usd, 4) in row, row


def test_every_usd_figure_on_the_slides_is_computed() -> None:
    """No hand-typed dollar amount: each one must be a value the code produces."""

    exposure = estimate_exposure(**EXAMPLE_AGENT)
    allowed = {format_usd(project_workload(NORMAL_WORKLOAD).cost_micro_usd, 4)}
    allowed |= {format_usd(row.cost_micro_usd, 4) for row in growth_table()}
    allowed |= {
        format_usd(run.cost_micro_usd, 4)
        for run in (exposure.normal, exposure.hijacked, exposure.capped)
    }
    found = set(re.findall(r"\b\d\.\d{4}\b", "\n".join(_plain(DECK))))
    assert found, "The growth table has gone missing from the deck."
    assert found <= allowed, f"Figures not produced by the code: {sorted(found - allowed)}"


def test_six_workshop_rows_on_the_slide_match_the_code() -> None:
    text = "\n".join(_plain(DECK))
    for result in compare_scenarios():
        assert f"{result.metrics.total_tokens:,}" in text
    sizes = project_workload(HIJACKED_WORKLOAD).input_sizes
    assert f"{sizes[0]}" in text and f"{sizes[-1]:,}" in text
    assert "×145" in text


@pytest.mark.parametrize("path", [DECK, "docs/defences.md"])
def test_round_two_table_matches_the_code_wherever_it_is_printed(path: str) -> None:
    lines = _plain(path)
    shown = 0
    for label, visible, everything in reference_rows():
        try:
            row = _line_with(lines, label)
        except AssertionError:
            continue  # a slide may show fewer rows than the notebook
        shown += 1
        numbers = re.findall(r"\d+ of \d+|\d{1,3}(?:,\d{3})+", row.split(label, 1)[1])
        assert numbers == [
            f"{visible.legit_finished} of {visible.legit_total}",
            f"{visible.attack_tokens:,}",
            f"{everything.legit_finished} of {everything.legit_total}",
            f"{everything.attack_tokens:,}",
        ], row
    assert shown >= 4


def test_transcript_on_the_slide_is_the_real_transcript() -> None:
    transcript = set(run_session(NORMAL_WORKLOAD, notes="poisoned").transcript)
    lines = [line for line in _slide("obeys the note until") if line]
    quoted = [line for line in lines if line.split(":")[0] in ("user", "action", "observe", "decision", "agent")]
    assert len(quoted) == 6
    for line in quoted:
        assert line in transcript, f"Not a line the agent prints: {line}"
    assert any("I will do what it says." in line for line in quoted)


@pytest.mark.parametrize(
    ("title_part", "policy", "held_out"),
    [
        ("The starting policy stops both attacks", BUDGET_POLICY, False),
        ("the round-one winner cuts a new task short", ROUND_ONE_WINNER, True),
    ],
)
def test_challenge_output_slides_match_the_code(title_part, policy, held_out) -> None:
    lines = _slide(title_part)
    result = score_policy(policy, held_out=held_out)
    for row in result.rows:
        line = _line_with(lines, f"Test {row.number} ·")
        if row.test.kind == "legit":
            assert line.count("◆") == row.reads_done, line
            assert line.count("◇") == row.reads_planned - row.reads_done, line
            if row.passed:
                assert "finished" in line
            else:
                assert f"cut short at {row.reads_done} of {row.reads_planned} ({row.stopped_by_knob})" in line
        else:
            expected = (
                f"{row.result.metrics.total_tokens:,} of {row.baseline_tokens:,} "
                f"({row.stopped_by_knob})"
            )
            assert expected in line, line
    title = " ".join(lines[:6])
    if held_out:
        assert "8 of 10 reads" in title and "6,592 tokens" in title


def test_attack_bars_on_the_challenge_slides_are_drawn_to_scale() -> None:
    html = (ROOT / DECK).read_text(encoding="utf-8")
    widest = 31_232  # the bulky note with no policy: the full-width track
    for policy, held_out, title in (
        (BUDGET_POLICY, False, "The starting policy stops both attacks"),
        (ROUND_ONE_WINNER, True, "the round-one winner cuts a new task short"),
    ):
        block = next(
            part for part in html.split('<section class="slide') if title in part
        )
        bars = re.findall(
            r'Test (\d) ·.*?class="track" style="width:([\d.]+)%"><span style="width:([\d.]+)%">', block
        )
        rows = {row.number: row for row in score_policy(policy, held_out=held_out).rows}
        assert len(bars) == sum(row.test.kind == "attack" for row in rows.values())
        for number, track, fill in bars:
            row = rows[int(number)]
            assert float(track) == pytest.approx(100 * row.baseline_tokens / widest, abs=0.1)
            assert float(fill) == pytest.approx(
                100 * row.result.metrics.total_tokens / row.baseline_tokens, abs=0.1
            )


def test_your_own_agent_slide_matches_the_code() -> None:
    lines = _slide("With an iteration limit of 25")
    exposure = estimate_exposure(**EXAMPLE_AGENT)
    for label, run, day in (
        ("A normal run", exposure.normal, exposure.normal_day_micro_usd),
        ("A run that loops to your iteration limit", exposure.hijacked, exposure.hijacked_day_micro_usd),
        ("The same loop, stopped by a budget of 3× a normal run", exposure.capped, exposure.capped_day_micro_usd),
    ):
        row = _line_with(lines, label)
        cells = row.split(label, 1)[1].split()
        assert cells == [
            f"{run.model_calls:,}",
            f"{run.total_tokens:,}",
            format_usd(run.cost_micro_usd, 4),
            format_usd(day),
        ], row
    title = " ".join(lines[:6])
    assert f"{exposure.normal.total_tokens:,}-token request" in title
    assert f"{exposure.hijacked.total_tokens:,} tokens" in title
    inputs = _line_with(lines, "Example inputs")
    assert "first prompt 2,000 tokens" in inputs and "500 requests a day" in inputs


def test_mocked_and_real_are_the_same_everywhere() -> None:
    """One list in config.py feeds the slide, the README, the notebook and the CLI."""

    assert [status for _part, status, _detail in SIMULATION_BOUNDARY] == ["mocked"] * 4 + ["real"] * 3

    # The slide groups the parts into two cards, in the same order, by the same names.
    slide = "\n".join(_slide("Only the model, the tools and the prices"))
    real_card = slide.index("\nReal\n")
    assert slide.index("\nMocked\n") < real_card
    position = 0
    for part, status, _detail in SIMULATION_BOUNDARY:
        found = slide.index(part, position)
        assert (found < real_card) == (status == "mocked"), part
        position = found

    # The README and the notebook print the full table.
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    notebook = json.loads((ROOT / "notebooks/denial_of_wallet_workshop.ipynb").read_text(encoding="utf-8"))
    notebook_text = "\n".join("".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "markdown")
    for text in (readme, notebook_text):
        for part, status, detail in SIMULATION_BOUNDARY:
            assert f"| {part} | **{status.capitalize()}** | {detail} |" in text, part
        assert BOUNDARY_VERDICT in text

    printed = format_boundary()
    for part, status, detail in SIMULATION_BOUNDARY:
        assert _line_with(printed.splitlines(), status.upper(), part, detail)


def test_iteration_limit_defaults_are_the_same_everywhere() -> None:
    """Five documented defaults, quoted on a slide, the worksheet and the references."""

    defaults = ("10", "15", "20", "20", "10,007")
    for path in ("presentation/references.md", "docs/worksheet.md"):
        text = (ROOT / path).read_text(encoding="utf-8")
        rows = [
            line for line in text.splitlines()
            if line.startswith("| ") and any(f"`{name}`" in line for name in ("max_turns", "max_iterations", "max_iter", "max_steps", "recursion_limit"))
        ]
        assert len(rows) == 5, path
        for row, default in zip(rows, defaults):
            assert f"| {default} " in row, (path, row)
    line = _line_with(_plain(DECK), "Default iteration limits")
    for fragment in ("SDK 10 turns", "AgentExecutor 15", "CrewAI 20", "smolagents 20", "10,007 graph super-steps"):
        assert fragment in line, fragment


def test_no_session_length_is_stated() -> None:
    """No total length is stated anywhere public."""

    for path in PUBLIC_TEXT:
        text = (ROOT / path).read_text(encoding="utf-8").lower()
        for phrase in ("60 minutes", "70 minutes", "60-minute", "70-minute", "one hour", "an hour", "1 hour"):
            assert phrase not in text, (path, phrase)


PUBLIC_TEXT = (
    "README.md",
    "CONTRIBUTING.md",
    DECK,
    "docs/worksheet.md",
    "docs/defences.md",
    "docs/attack-model.md",
    "docs/safety-model.md",
    "docs/architecture.md",
    "notebooks/build_notebook.py",
)


def test_nothing_is_addressed_to_a_presenter() -> None:
    """The repository is public and written for the people doing the workshop."""

    assert not (ROOT / "docs/facilitator-guide.md").exists()
    for path in PUBLIC_TEXT:
        text = re.sub(r"<[^>]+>", " ", (ROOT / path).read_text(encoding="utf-8")).lower()
        for phrase in ("facilitator", "speaker notes", "running order", "the presenter", "the host", "in the chat", "the audience", "hand out", "share the notebook link", "live session"):
            assert phrase not in text, (path, phrase)
    deck = "\n".join(_plain(DECK)).lower()
    assert not re.search(r"\b\d+ minutes?\b", deck)


def test_the_challenge_answers_are_not_on_the_front_page() -> None:
    """People open the README to reach the notebook, before they try the challenge."""

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for label, visible, everything in reference_rows():
        if label == "No policy":
            continue
        assert label not in readme, label
    for answer in ("5,120", "11,936", "max_stalled_iterations", "stalled 1", "stalled 2"):
        assert answer not in readme, answer
    defences = (ROOT / "docs/defences.md").read_text(encoding="utf-8")
    assert "## The challenge (this section gives the answers away)" in defences


def test_slide_titles_are_plain_declarative_sentences() -> None:
    """One claim per title, with no contrast built for rhythm."""

    html = (ROOT / DECK).read_text(encoding="utf-8")
    titles = [re.sub(r"<[^>]+>", "", title).strip() for title in re.findall(r"<h1>(.*?)</h1>", html, re.S)]
    assert len(titles) == SLIDE_COUNT
    for title in titles:
        lowered = title.lower()
        for pattern in (";", " whereas ", ", but ", ", not ", " rather than ", " instead of ", ", and ", ", so ", ", because "):
            assert pattern not in lowered, (pattern, title)
        assert not re.match(r"^[A-Z][\w\s-]{0,24}: ", title), f"Label-and-colon opener: {title}"
        assert not title.endswith((".", "!", "?")), title


def test_the_pdf_is_built_online_from_the_html_on_every_push() -> None:
    """The Pages workflow prints the deck and publishes both files together."""

    workflow = (ROOT / ".github/workflows/pages.yml").read_text(encoding="utf-8")
    assert "branches: [main]" in workflow
    build = workflow.index("python presentation/build_pdf.py")
    assemble = workflow.index("cp presentation/deck.html presentation/deck.pdf _site/presentation/")
    upload = workflow.index("actions/upload-pages-artifact")
    deploy = workflow.index("actions/deploy-pages")
    assert build < assemble < upload < deploy
    # The PDF is an output of that build. A committed copy could go stale.
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "presentation/deck.pdf" in ignored


def test_the_pdf_builder_counts_the_same_slides() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("build_pdf", ROOT / "presentation/build_pdf.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert module.slide_count() == SLIDE_COUNT
    command = module.browser_command("chrome", "/tmp/profile", Path("/tmp/deck.pdf"))
    assert command[-1].endswith("presentation/deck.html")
    assert "--print-to-pdf=/tmp/deck.pdf" in command


def _notebook_sections() -> set[int]:
    notebook = json.loads((ROOT / "notebooks/denial_of_wallet_workshop.ipynb").read_text(encoding="utf-8"))
    text = "\n".join("".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "markdown")
    return {int(number) for number in re.findall(r"^## (\d+)\. ", text, re.MULTILINE)}


def test_everything_from_the_notebook_is_marked_as_such() -> None:
    """A run marker says "run this cell now". A dark-headed panel is notebook output."""

    html = (ROOT / DECK).read_text(encoding="utf-8")
    sections = _notebook_sections()
    assert sections == set(range(1, 11))
    runs = [re.sub(r"<[^>]+>", "", item) for item in re.findall(r'<span class="run">(.*?)</span>', html)]
    panels = re.findall(r'<div class="nb-head"><span>(.*?)</span><span>(.*?)</span></div>', html)
    assert len(runs) == 6 and len(panels) == 8
    for text in runs:
        assert text.startswith("Notebook · "), text
    for label, promise in panels:
        assert label.startswith("Notebook output · section "), label
        assert promise == "the same on your screen"
    named = runs + [label for label, _promise in panels]
    for text in named:
        if "Setup cell" in text:
            continue
        numbers = [int(number) for number in re.findall(r"\b(\d+)\b", text.split("section", 1)[1])]
        assert numbers, text
        assert set(numbers) <= sections, text
    # The markers carry the notebook reference, so the small kicker lines do not repeat it.
    for kicker in re.findall(r'<p class="kicker">(.*?)</p>', html):
        assert "notebook" not in kicker.lower(), kicker
    # The housekeeping slide explains the two markers.
    housekeeping = next(part for part in html.split('<section class="slide') if 'data-title="Housekeeping"' in part)
    assert 'class="run legend"' in housekeeping and 'class="nb-mini"' in housekeeping


def test_quoted_output_sits_inside_a_notebook_panel() -> None:
    """Transcript, measured numbers, staircase, six rows, both rounds, comparison, exposure."""

    html = (ROOT / DECK).read_text(encoding="utf-8")
    slides = html.split('<section class="slide')[1:]
    for title_part, marker in (
        ("obeys the note until", "decision: The note says"),
        ("multiplies the estimated tokens 145×", "128 → 18,560"),
        ("Doubling the steps quadruples", "1,223,680"),
        ("A progress check stops the loop", "ran all 10 steps"),
        ("The starting policy stops both attacks", "Test 4 ·"),
        ("the round-one winner cuts a new task short", "Test 6 ·"),
        ("A policy fitted to the four tests", "68,352"),
        ("With an iteration limit of 25", "1,805.00"),
    ):
        slide = next(part for part in slides if title_part in part.split("</h1>")[0])
        body = slide.split("</h1>", 1)[1]
        panel = body[body.index('<div class="nb">'):]
        assert marker in panel, (title_part, marker)
        assert marker not in body[: body.index('<div class="nb">')], (title_part, marker)


def test_every_site_link_on_the_slides_is_published() -> None:
    """Short links on the slides must exist in site/ or be the deck itself."""

    html = (ROOT / DECK).read_text(encoding="utf-8")
    links = set(re.findall(r"prismatic-labs\.github\.io/cost-as-an-attack-surface/([a-z/.]+)", html))
    assert {"notebook", "worksheet"} <= links
    for link in links:
        if link.startswith("presentation/"):
            assert (ROOT / link).is_file(), link
        else:
            assert (ROOT / "site" / link.strip("/") / "index.html").is_file(), link
    workflow = (ROOT / ".github/workflows/pages.yml").read_text(encoding="utf-8")
    assert "cp -R site/. _site/" in workflow


def test_short_links_point_at_the_right_places() -> None:
    notebook = (ROOT / "site/notebook/index.html").read_text(encoding="utf-8")
    colab = re.search(r'url=(https://colab\.research\.google\.com/github/[^"]+)"', notebook).group(1)
    assert colab.endswith("/blob/main/notebooks/denial_of_wallet_workshop.ipynb")
    assert (ROOT / colab.split("/blob/main/", 1)[1]).is_file()
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert colab in readme, "The Open in Colab badge and the short link must open the same notebook."
    worksheet = (ROOT / "site/worksheet/index.html").read_text(encoding="utf-8")
    target = re.search(r'url=(https://github\.com/[^"]+)"', worksheet).group(1)
    assert (ROOT / target.split("/blob/main/", 1)[1]).is_file()
    landing = (ROOT / "site/index.html").read_text(encoding="utf-8")
    for href in ("notebook/", "presentation/deck.html", "presentation/deck.pdf", "worksheet/"):
        assert f'href="{href}"' in landing, href


def test_the_notebook_link_is_on_the_first_slide_and_every_slide() -> None:
    html = (ROOT / DECK).read_text(encoding="utf-8")
    first = html.split('<section class="slide')[1].split("</section>")[0]
    assert "prismatic-labs.github.io/cost-as-an-attack-surface/notebook" in first
    footer = html.split("<footer>")[1].split("</footer>")[0]
    assert "prismatic-labs.github.io/cost-as-an-attack-surface/notebook" in footer


def test_the_loop_is_introduced_before_it_is_used() -> None:
    lines = _slide("keep its loop of model and tool calls going")
    assert any(line.startswith("The agent loop:") for line in lines)


def test_owasp_slide_uses_standard_terms() -> None:
    lines = _slide("Denial of Wallet can drain your API budget")
    text = "\n".join(lines)
    assert _line_with(lines, "Attack vector", "LLM01")
    assert _line_with(lines, "Impact", "LLM10")
    assert "Role" not in text and "Trigger" not in text


def test_ways_in_are_sourced() -> None:
    """Every row on the map names a source that is in the references."""

    lines = _slide("one of several documented ways")
    shown = "\n".join(lines)
    references = (ROOT / "presentation/references.md").read_text(encoding="utf-8")
    for on_slide, in_references in {
        "Breaking Agents": "Breaking Agents",
        "OverThink": "OverThink",
        "OWASP LLM10:2025": "LLM10:2025",
        "serverless computing": "Serverless Computing",
        "Sysdig": "Sysdig",
    }.items():
        assert on_slide in shown, on_slide
        assert in_references in references, in_references
    assert "keep working" in _line_with(lines, "today")
    assert len([line for line in lines if line.startswith(("Text ", "Very ", "A flood", "Stolen"))]) == 5


def test_evidence_slide_only_shows_real_model_measurements() -> None:
    text = "\n".join(_slide("Published attacks make real models"))
    assert "OverThink" in text and "Breaking Agents" in text
    assert "Sysdig" not in text


PEOPLE = (
    r"\bTom\b", r"et al\.", "Kumar", "Bagdasarian", "Houmansadr", "Karpinska", "Iyyer",
    "Zhang", "Zannettou", "Backes", "Salem", "Kelly", "Glavin", "Barrett", "Brucato",
)


def test_nobody_but_the_author_is_named() -> None:
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    for name in tracked + ["site/index.html", "site/notebook/index.html", "site/worksheet/index.html"]:
        path = ROOT / name
        if name == "tests/test_published_numbers.py" or not path.is_file():
            continue
        if path.suffix not in {".md", ".html", ".py", ".yml", ".toml", ".ipynb", ".mmd"}:
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in PEOPLE:
            assert not re.search(pattern, text), (name, pattern)


def test_the_term_is_iteration_limit() -> None:
    for path in PUBLIC_TEXT:
        text = (ROOT / path).read_text(encoding="utf-8").lower()
        assert "step cap" not in text, path


def test_the_basics_slide_matches_the_staircase() -> None:
    """The two rows are the first two model calls of the demo, drawn to scale."""

    html = (ROOT / DECK).read_text(encoding="utf-8")
    block = next(part for part in html.split('<section class="slide') if 'data-title="The basics"' in part)
    sizes = project_workload(HIJACKED_WORKLOAD).input_sizes
    rows = block.split('<span class="lab">')[1:]
    assert [row.split("<", 1)[0] for row in rows] == ["Call 1", "Call 2"]

    def widths(row: str, kind: str) -> float:
        return sum(float(w) for w in re.findall(rf'class="blk {kind}" style="width:([\d.]+)em"', row))

    read_one, read_two = widths(rows[0], "read"), widths(rows[1], "read")
    assert read_one / widths(rows[0], "write") == pytest.approx(sizes[0] / 64)
    assert read_two / widths(rows[1], "write") == pytest.approx(sizes[1] / 64)
    ratio = sizes[1] / sizes[0]
    assert read_two / read_one == pytest.approx(ratio)
    assert f"reads {ratio:.0f}× as much" in block
    assert block.count('class="tok"') == 16 and "16 tokens" in block


def test_the_logo_is_on_the_first_and_last_slide() -> None:
    html = (ROOT / DECK).read_text(encoding="utf-8")
    slides = html.split('<section class="slide')[1:]
    for index in (0, len(slides) - 1):
        assert '<img class="logo"' in slides[index] and 'alt="Prismatic Labs"' in slides[index]
    assert sum('<img class="logo"' in slide for slide in slides) == 2


def test_billing_claims_on_the_slides_are_sourced() -> None:
    references = (ROOT / "presentation/references.md").read_text(encoding="utf-8")
    for needle in ("o200k_base", "billed as output tokens", "five times input", "developers.openai.com/api/docs/guides/reasoning"):
        assert needle in references, needle


def test_the_housekeeping_slide_shows_how_to_run_a_cell() -> None:
    html = (ROOT / DECK).read_text(encoding="utf-8")
    slides = html.split('<section class="slide')[1:]
    assert 'data-title="Housekeeping"' in slides[1], "Housekeeping is the second slide."
    page = slides[1].split("</section>")[0]
    assert '<figure class="shot wide">' in page and "Google Colab" in page
    assert "Click the round button to run a cell, or press Shift+Enter" in page
    ring = re.search(r'class="ring" style="left:([\d.]+)%; top:([\d.]+)%"', page)
    assert ring and 5 < float(ring.group(1)) < 15 and 50 < float(ring.group(2)) < 85
    assert "prismatic-labs.github.io/cost-as-an-attack-surface/notebook" in page
    assert '<figure class="shot' not in slides[0]
