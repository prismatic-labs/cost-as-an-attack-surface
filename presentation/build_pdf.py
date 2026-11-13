"""Print presentation/deck.html to presentation/deck.pdf, one slide per page.

    python presentation/build_pdf.py

The HTML deck is the only source for the slides. The Pages workflow runs this
script on every push and publishes the PDF next to the HTML, so the two are
always the same version. Run it yourself only to preview the PDF or to keep a
copy offline. The PDF is not committed.

It needs Google Chrome, Chromium or Microsoft Edge on the machine. Set the
CHROME environment variable to the browser's path if it is not found. The
deck loads its fonts from Google Fonts, so build with a network connection.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DECK = HERE / "deck.html"
PDF = HERE / "deck.pdf"

BROWSERS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "chrome",
    "msedge",
)


def slide_count() -> int:
    return DECK.read_text(encoding="utf-8").count('<section class="slide')


def page_count(pdf: Path) -> int:
    return len(re.findall(rb"/Type\s*/Page(?![a-zA-Z])", pdf.read_bytes()))


def find_browser() -> str:
    chosen = os.environ.get("CHROME")
    candidates = (chosen,) if chosen else BROWSERS
    for candidate in candidates:
        if not candidate:
            continue
        if Path(candidate).is_file():
            return candidate
        found = shutil.which(candidate)
        if found:
            return found
    raise SystemExit(
        "No Chromium browser found. Install Google Chrome, or set CHROME to the "
        "path of Chrome, Chromium or Edge."
    )


def browser_command(browser: str, profile: str, target: Path) -> list[str]:
    command = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--no-pdf-header-footer",
        f"--user-data-dir={profile}",
        "--virtual-time-budget=10000",
        f"--print-to-pdf={target}",
    ]
    if os.environ.get("CI"):
        # Hosted runners do not always allow the browser's own sandbox. The
        # only page opened here is the deck from this repository.
        command.append("--no-sandbox")
    command.append(DECK.as_uri())
    return command


def main() -> None:
    browser = find_browser()
    with tempfile.TemporaryDirectory() as profile:
        target = Path(profile) / "deck.pdf"
        done = subprocess.run(
            browser_command(browser, profile, target),
            capture_output=True,
            text=True,
            timeout=180,
        )
        if done.returncode != 0 or not target.is_file():
            sys.stderr.write(done.stderr)
            raise SystemExit("The browser did not produce a PDF.")
        pages, slides = page_count(target), slide_count()
        if pages != slides:
            raise SystemExit(
                f"The PDF has {pages} pages for {slides} slides. Check the print "
                "styles in deck.html, then build again."
            )
        shutil.copyfile(target, PDF)
    print(f"Wrote {PDF} ({pages} pages) from {DECK.name}")


if __name__ == "__main__":
    main()
