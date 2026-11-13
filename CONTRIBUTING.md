# Contributing

This repository is an educational workshop. Changes should make the experiment clearer, safer, or easier to reproduce.

## Ground rules

- The package stays runnable without an API key, without a paid inference service, and without a network connection.
- Do not add a dependency on a Prismatic Labs product, SDK, or hosted API. Attribution in the documentation is welcome. A product integration is not.
- Do not add network calls anywhere in the package. A test scans the source for network clients.
- Do not raise `SafetyCeilings` casually. A higher ceiling needs a short note in `docs/safety-model.md` explaining why the classroom bound is still safe.
- Keep illustrative money labelled with `ILLUSTRATIVE SIMULATED COST. NOT AN ACTUAL API BILL.`
- No em-dashes in prose or code. A test checks.
- A slide title is one plain declarative sentence that states the slide's point. No contrast or pairing built for rhythm: no semicolons, no "whereas", no "X, but Y", no "X, not Y", no second clause hung on a comma ("X, and Y", "X, so Y", "X, because Y"), and no "Label: sentence" openers. A test checks the patterns it can.
- Name no person in this repository except the workshop's author. Cite papers by title, arXiv number and date, and reports by the organisation that published them.
- For the most model calls a framework lets one request make, say "iteration limit". Each framework has its own name for it (`max_turns`, `max_iterations`, `max_steps`), and the worksheet lists them.
- Write every page for the people doing the workshop.

## Local check

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,notebook]"
pytest
python -m dow_workshop
```

On Windows, activate the virtual environment with `.venv\Scripts\activate`.

## Pull requests

- Describe the teaching change, not only the code change.
- Notebook prose lives in `notebooks/build_notebook.py`. That script is canonical. Regenerate `notebooks/denial_of_wallet_workshop.ipynb` from it after an edit. A test fails if the two drift.
- If a default changes, the numbers in `README.md`, `docs/`, and `presentation/` change with it. The tests assert the published figures, so start there. `tests/test_published_numbers.py` reads the slides and the README back and compares every table with the code.
- A new claim about real models or real products needs a source you have opened, listed in `presentation/references.md` with the date you checked it.
- The slides are `presentation/deck.html`, one self-contained file. The Pages workflow prints it to PDF on every push and publishes both, together with the short links in `site/`, so do not commit a PDF. Run `python presentation/build_pdf.py` to preview one.
- On a slide, anything that comes from the notebook carries a marker: a `run` pill for "run that cell now", or an `nb` panel around a copy of the notebook's output. A test checks both.
- What is mocked and what is real is one list, `SIMULATION_BOUNDARY` in `config.py`. Change it there, and the tests will tell you where else it is printed.
- Do not commit `.env` files, notebook outputs, or checkpoints.

## Attribution

Workshop materials: Copyright 2026 Prismatic Labs, Apache License 2.0.
