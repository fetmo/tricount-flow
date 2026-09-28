# Contributing to tricount-flow

Thanks for your interest! This is a small, focused tool — contributions that keep it
simple and well-tested are very welcome.

## Ground rules

- **The API is unofficial.** All calls to Tricount's private API live in one place:
  `src/tricount_flow/core.py`. If the API changes, that's the file to fix. Please
  don't scatter API calls across the CLI or web layers.
- **Keep the layers thin.** `cli.py` and `web/app.py` should only translate
  input/output; business logic belongs in `core.py`, parsing in `csvio.py`, and pure
  math in `settle.py`.
- **No credentials or share links in commits, tests, or issues.** Ever.

## Development setup

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12+.

```bash
uv sync --group dev
uv run pytest            # tests
uv run ruff check .      # lint
uv run ruff format .     # format
```

## Making a change

1. Fork and branch off `main`.
2. Add or update tests — pure logic (`settle.py`, `csvio.py`, config, dates) is
   unit-tested without any network access; please keep it that way.
3. Run `uv run pytest` and `uv run ruff check .` before opening a PR.
4. Describe *what* and *why* in the PR. Screenshots help for web UI changes.

## Reporting bugs

Open an issue with steps to reproduce. If it's an API-shape change (a call suddenly
failing), please include the failing command and the error text — but **redact any
tokens or share links**.
