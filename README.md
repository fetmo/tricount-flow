# tricount-flow

[![CI](https://github.com/fetmo/tricount-flow/actions/workflows/ci.yml/badge.svg)](https://github.com/fetmo/tricount-flow/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)

Add expenses and check balances on a [Tricount](https://tricount.com) from your
laptop — a fast **CLI** and a small **local web UI** — instead of picking up your
phone every time.

Since bunq (which owns Tricount) removed the web version, there's no official way
to do this. `tricount-flow` is a thin, laptop-friendly layer over the
community-maintained [`tricount-api`](https://pypi.org/project/tricount-api/),
which talks to Tricount's **private, reverse-engineered API**.

> ⚠️ **Unofficial & unsupported.** This uses an undocumented API that bunq can
> change or block at any time, and is outside Tricount's Terms of Service. There
> is also **no per-user identity**: anyone with a tricount's share link can read
> and edit it, and every change you make is applied to the shared tricount for
> **everyone**, immediately. Use it for your own tricounts, at your own risk.

## Install

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12+.

```bash
uv sync
```

Run commands with `uv run tricount ...` (or `uv run tricount` after activating the
venv).

## Setup

```bash
uv run tricount init
```

Paste your tricount's share link (`https://tricount.com/tXXXX` — get it from the
app's *Share* button), pick which member *you* are, and give it a short name.
Config is stored at `~/.config/tricount-flow/config.toml`; the device credential
is stored beside it and is **never** committed.

You can add several tricounts (e.g. `household`, `trip`) and switch with `--for`.
Each has a short **alias** — its stable id used everywhere (`--for`, scripts, the
`$TRICOUNT` env var).

## CLI usage

```bash
# Add an expense (defaults: you paid today, split equally among everyone)
uv run tricount add "Dinner" 45
uv run tricount add "Groceries" 32.50 --payer Anna --category groceries
uv run tricount add "Taxi" 20 --split Moritz,Anna --for trip
uv run tricount add "Coffee" 4.20 --date 25.09              # backdate (also 2026-09-25)
uv run tricount add "Hotel" 300 --dry-run                   # preview, don't send

# Who owes whom (+ suggested payments)
uv run tricount balances
uv run tricount balances --for trip

# Record a payback (you paid Anna 20 back, optionally on a past date)
uv run tricount reimburse 20 --to Anna
uv run tricount reimburse 20 --to Anna --date 25.09

# Recent expenses / valid categories
uv run tricount list -n 15
uv run tricount categories
```

Amounts are in the tricount's currency (e.g. `45` = €45). Dates accept `DD.MM`,
`DD.MM.YYYY`, or ISO `YYYY-MM-DD` (default: today). Categories accept the built-in
names (`GROCERIES`, `TRANSPORT`, …) or friendly aliases (`food`, `rent`, `fun`, …);
anything else becomes a custom label.

## Managing tricounts

```bash
uv run tricount tricounts                                   # list them
uv run tricount tricounts add https://tricount.com/tXXXX --alias trip --me Moritz --default
uv run tricount tricounts show trip                         # live title/currency/members
uv run tricount tricounts set-me trip Moritz               # set who "you" are
uv run tricount tricounts set-default household
uv run tricount tricounts rename trip vacation
uv run tricount tricounts remove vacation
```

`tricounts add` is the non-interactive counterpart to `init` — ideal for scripts.
Aliases are stable; renaming one updates the default automatically if needed.

## Import from CSV

Bulk-add expenses (great for backfilling past spending from a spreadsheet):

```bash
uv run tricount import expenses.csv                 # previews, then asks to confirm
uv run tricount import expenses.csv --dry-run       # validate only, send nothing
uv run tricount import expenses.csv --for trip --payer Moritz --yes
```

The format is lenient (see [`examples/expenses.csv`](examples/expenses.csv)):

| column | required | notes |
|---|---|---|
| `description` | ✅ | |
| `amount` | ✅ | EU or US decimals & currency symbols (`12,50`, `€1.234,56`) |
| `payer` | | defaults to you |
| `split` | | members separated by `\|`; defaults to everyone |
| `category` | | name or alias; else a custom label |
| `date` | | `DD.MM`, `DD.MM.YYYY`, or ISO; defaults to today |
| `type` | | `reimbursement` marks a payback (needs `to`) |
| `to` | | receiver for a reimbursement |

Headers are case-insensitive with common aliases; the delimiter (`,`/`;`/tab) is
auto-detected. Bad rows are reported and skipped — the rest still import. The web UI
has the same import (with a preview) under **Import CSV**.

## Automation

Everything is scriptable:

```bash
# JSON output on the read commands
uv run tricount balances --json
uv run tricount list --json
uv run tricount tricounts --json

# Pick the target tricount without --for, e.g. for cron jobs
TRICOUNT=household uv run tricount add "Rent" 1200 --category rent --date 01.10
```

Target selection precedence: `--for` > `$TRICOUNT` > the configured default.

## Web UI

```bash
uv run tricount web            # serves http://localhost:8787 and opens a browser
uv run tricount web --port 9000 --no-browser
```

A single page: pick a tricount, add an expense (payer + split checkboxes),
record reimbursements, and see live balances and settlement suggestions. Handy
for a non-technical partner — it runs entirely on your machine.

## How it works

```
cli.py ─┐
        ├─> core.py ──> tricount-api ──> api.tricount.bunq.com   (the ONLY file
web/    ─┘                                                        touching the API)
```

- `core.py` is the single choke point for every API call — if the private API
  changes, that's the one place to fix.
- `settle.py` computes minimal "who pays whom" suggestions (kept local, so it
  needs no bunq bank account).
- `csvio.py` is a dependency-free, lenient CSV parser.
- `config.py` handles the config file and share-link/token parsing.

**Design choices worth calling out:**

- **One API boundary.** The CLI and web UI are thin adapters over `core.py`; the
  fragile, unofficial API is isolated behind it. Swapping or fixing the backend
  touches one file.
- **Pure logic is network-free and unit-tested.** Settlement, CSV parsing, date
  parsing, and config mutations have no I/O, so the test suite runs offline in
  ~0.2s and covers the tricky parts (EU/US decimals, minimal-transfer netting,
  default-reassignment on rename/remove).
- **Best-effort imports.** A malformed CSV row is reported and skipped; the rest
  still import — with a dry-run preview before anything is sent.
- **Safety by default.** Writes hit shared data, so create/import commands preview
  and confirm, and `--dry-run` is everywhere.

## Development

```bash
uv sync --group dev
uv run pytest            # tests (offline)
uv run ruff check .      # lint
uv run ruff format .     # format
```

CI (GitHub Actions) runs lint, format-check, and tests on Python 3.12 and 3.13.

## Credits

Built on the reverse-engineering work of the Tricount community, especially
[`tricount-api`](https://pypi.org/project/tricount-api/). Not affiliated with or
endorsed by Tricount or bunq.
