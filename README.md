# annual-report-evaluation

Evaluates the quality of LLM-based PDF extraction against XBRL ground truth
data for annual financial reports.

---

## Table of contents

1. [What it does](#what-it-does)
2. [How it works](#how-it-works)
3. [Project layout](#project-layout)
4. [Setup](#setup)
5. [Usage](#usage)
6. [Output schema](#output-schema)
7. [Metrics reference](#metrics-reference)
8. [Run log](#run-log)
9. [Limitations](#limitations)
10. [Development](#development)

---

## What it does

`annual-report-evaluation` sits downstream of two independent extraction
pipelines and answers a single question:

> **How accurately does the LLM-based PDF pipeline recover the financial facts
> that the deterministic XBRL pipeline extracts from the same filing?**

It takes one JSON from each pipeline for the same company and fiscal year,
reconciles the facts using a two-tier matching strategy, and produces a
structured evaluation report with coverage, accuracy, and precision/recall/F1
scores — broken down by financial statement.

**Does:**

- Normalise both sources to plain absolute dollars before any comparison.
- Match facts first by exact XBRL concept name, then by canonical name (fallback).
- Score coverage, value accuracy at three tolerance tiers (exact / ±1% / ±5%),
  and precision/recall/F1 at the canonical level.
- Write a machine-readable JSON report and a human-scannable diff text file.
- Log every run to an append-only `run_log.jsonl`.

**Does not:**

- Call any LLM or external API.
- Modify or re-run the upstream extraction pipelines.
- Perform cross-company or time-series analysis.
- Match segment or dimensional facts (v1: primary statements only).

**v1 scope — statements covered:**
Income Statement · Balance Sheet · Cash Flow Statement · PPE Note

---

## How it works

### Input pair

| File                                  | Source       | Role                         |
| ------------------------------------- | ------------ | ---------------------------- |
| `*.facts.json` from `pdf-extraction`  | LLM pipeline | **Subject under evaluation** |
| `*.facts.json` from `xbrl-extraction` | iXBRL parser | **Ground truth**             |

Both files must cover the same company and fiscal year.

### Normalisation

`pdf-extraction` values carry a `scale` string (`"millions"`, `"thousands"`,
`"billions"`, `"actual"`). `xbrl-extraction` values carry a `scale` integer
string (`"6"` = 10⁶, `"3"` = 10³). Both are converted to plain absolute
dollars before any comparison.

### Two-tier join

The reconciler matches PDF facts to XBRL facts using priority order:

**Tier 1 — concept match:** `pdf_fact.concept == xbrl_fact.concept`
(e.g. `"us-gaap:Revenues"` ↔ `"us-gaap:Revenues"`). Exact string equality only.

**Tier 2 — canonical fallback:** If no Tier 1 match is found, compare the
PDF fact's `canonical` field against the XBRL concept's human label (from
`labs.json` if available). Case-insensitive, stripped. Logged with
`match_tier: 2` for inspection.

Facts with no match in either tier are classified as `missed` (XBRL fact not
recovered by PDF pipeline) or `spurious` (PDF fact with no XBRL counterpart).

### Scoring

Three metric families computed from the matched/missed/spurious sets:

1. **Coverage** — what fraction of XBRL facts the PDF pipeline recovered.
2. **Value accuracy** — for matched pairs, % exact / within 1% / within 5%.
3. **Precision / Recall / F1** — at the canonical level, per statement and overall.

---

## Project layout

```
annual-report-evaluation/
├── README.md
├── CHANGELOG.md
├── pyproject.toml
├── Makefile
│
├── src/
│   └── annual_report_evaluation/
│       ├── cli.py              # argparse — single pair + batch
│       ├── schema.py           # FinancialFact, EvaluationReport, ScoreResult
│       ├── adapters/
│       │   ├── pdf_adapter.py  # pdf-extraction JSON → List[FinancialFact]
│       │   └── xbrl_adapter.py # xbrl-extraction JSON → List[FinancialFact]
│       ├── reconciler.py       # two-tier join → matched / missed / spurious
│       ├── scorer.py           # coverage, accuracy, precision/recall/F1
│       ├── reporter.py         # JSON report + diff text writers
│       ├── logger.py           # append-only run_log.jsonl
│       └── utils.py            # normalise_value(), period_overlap()
│
├── data/
│   ├── input/
│   │   ├── pdf/                # pdf-extraction JSONs go here
│   │   └── xbrl/               # xbrl-extraction JSONs go here
│   └── output/                 # evaluation reports written here
│
├── logs/
│   └── run_log.jsonl
│
└── tests/
    ├── fixtures/               # synthetic sample JSONs for unit tests
    ├── test_adapters.py
    ├── test_reconciler.py
    ├── test_scorer.py
    └── test_reporter.py
```

---

## Setup

Requires Python 3.10+. Everything runs inside a project-local virtualenv at
`.venv/`. The `Makefile` handles the bootstrap and works on Linux, macOS,
and Windows (with GNU Make installed).

### Quick start

```bash
git clone <repo>
cd annual-report-evaluation
make install
```

That's it. `make install` does three things:

1. Creates `.venv/` if it doesn't exist (`python3 -m venv .venv` on Unix,
   `python -m venv .venv` on Windows)
2. Upgrades `pip` and installs `wheel` inside it
3. Editable-installs this package with its dev dependencies (`pip install -e ".[dev]"`)

A stamp file at `.venv/.installed` makes the target idempotent — subsequent
`make install` calls are no-ops unless `pyproject.toml` has changed.

### Windows notes

The `Makefile` auto-detects Windows via `$(OS)` and uses `.venv\Scripts\`
paths and `python` (instead of `.venv/bin/` and `python3` on Unix). You
need a working `make` on PATH — install one of:

- [`make` via chocolatey](https://chocolatey.org/): `choco install make`
- [`make` via scoop](https://scoop.sh/): `scoop install make`
- Git for Windows bundled `make` (in Git Bash)

If you don't have `make`, you can run the underlying commands manually:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip wheel
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

### Activating the venv (optional)

You don't need to activate the venv to use the `make` targets — they all
run through the venv's Python directly. But if you want to invoke
`evaluate-report` or `pytest` by hand, activate first:

```bash
# Linux / macOS
source .venv/bin/activate

# Windows (PowerShell)
.venv\Scripts\Activate.ps1

# Windows (cmd)
.venv\Scripts\activate.bat
```

To exit: `deactivate`.

### Installing the upstream extraction packages

The two upstream packages (`pdf-extraction` and `xbrl-extraction`) are listed
as an **optional** extra in `pyproject.toml`, because:

- They are not on PyPI — they live in sibling git repositories.
- This package never imports them; it only reads the JSON files they produce.

You only need to install them when you want to _regenerate_ the input JSONs
(e.g. extract a new PDF). For evaluating pre-generated JSONs, skip this step.

If you do want them installed:

```bash
make install-upstream
# or, with explicit paths:
make PDF_EXTRACTION=/path/to/pdf-extraction \
     XBRL_EXTRACTION=/path/to/xbrl-extraction \
     install-upstream
```

No API keys required — the evaluation layer makes no external calls.

### Choosing a different venv location

```bash
make VENV=.venv-dev install
make VENV=.venv-dev test
```

---

## Usage

The examples below assume you've run `make install`. You can invoke the CLI
in three equivalent ways:

```bash
# 1. via Make (no venv activation needed)
make evaluate PDF=path/to.pdf.json XBRL=path/to.xbrl.json

# 2. through the venv's Python directly
.venv/bin/python -m annual_report_evaluation --pdf ... --xbrl ...

# 3. after activating the venv, use the installed console script
source .venv/bin/activate
evaluate-report --pdf ... --xbrl ...
```

### Single pair

```bash
evaluate-report \
  --pdf  data/input/pdf/AAPL_FY2024.facts.json \
  --xbrl data/input/xbrl/aapl.facts.json \
  --out  data/output/
```

Output:

```
Evaluating AAPL FY2024...

  XBRL facts in scope:  120
  PDF facts in scope:   115
  Matched:               98  (Tier 1: 85 · Tier 2: 13)
  Missed:                22
  Spurious:              17

  Coverage:   81.7%
  Precision:  85.2%  Recall:  81.7%  F1:  83.4%
  Exact:      71.4%  ≤1%:  79.6%  ≤5%:  85.7%

  → wrote AAPL_FY2024.evaluation.json
  → wrote AAPL_FY2024.evaluation.diff.txt
```

### Batch mode

```bash
evaluate-report \
  --pdf-dir  data/input/pdf/ \
  --xbrl-dir data/input/xbrl/ \
  --out      data/output/
```

Files are auto-matched by `ticker` + `fiscal_year` parsed from each JSON's
metadata. Unmatched files are logged as warnings and skipped.

### Dry run

```bash
evaluate-report --pdf ... --xbrl ... --dry-run
```

Prints what would be evaluated without writing any output files.

---

## Output schema

### `*.evaluation.json`

```json
{
  "meta": {
    "ticker": "AAPL",
    "fiscal_year": 2024,
    "period_end": "2024-09-28",
    "pdf_source": "AAPL_FY2024.facts.json",
    "xbrl_source": "aapl.facts.json",
    "evaluated_at": "2026-05-19T10:00:00Z",
    "scope": ["IncomeStatement", "BalanceSheet", "CashFlow", "Note_PPE"]
  },
  "summary": {
    "xbrl_facts_in_scope": 120,
    "pdf_facts_in_scope": 115,
    "matched": 98,
    "missed": 22,
    "spurious": 17,
    "tier1_matches": 85,
    "tier2_matches": 13
  },
  "scores": {
    "overall": {
      "coverage": 0.817,
      "precision": 0.852,
      "recall": 0.817,
      "f1": 0.834,
      "exact_match_rate": 0.714,
      "within_1pct_rate": 0.796,
      "within_5pct_rate": 0.857
    },
    "by_statement": {
      "IncomeStatement": {
        "coverage": 0.91,
        "precision": 0.93,
        "recall": 0.91,
        "f1": 0.92,
        "exact_match_rate": 0.8,
        "within_1pct_rate": 0.87,
        "within_5pct_rate": 0.91
      },
      "BalanceSheet": { "...": "..." },
      "CashFlow": { "...": "..." },
      "Note_PPE": { "...": "..." }
    }
  },
  "facts": [
    {
      "canonical": "Revenue",
      "concept": "us-gaap:Revenues",
      "statement": "IncomeStatement",
      "status": "matched",
      "match_tier": 1,
      "pdf_value": 391035000000,
      "xbrl_value": 391035000000,
      "absolute_error": 0,
      "pct_error": 0.0,
      "exact_match": true,
      "within_1pct": true,
      "within_5pct": true
    }
  ]
}
```

### `*.evaluation.diff.txt`

Human-readable per-statement diff. Each fact line uses one of six status markers:

| Marker      | Meaning                               |
| ----------- | ------------------------------------- |
| `[MATCH ✓]` | Exact match — `pct_error == 0`        |
| `[CLOSE ~]` | Within 1% error                       |
| `[DRIFT !]` | Within 5%, outside 1%                 |
| `[LARGE ⚠]` | Error > 5%                            |
| `[MISS  ✗]` | XBRL fact not found in PDF output     |
| `[EXTRA +]` | PDF fact not found in XBRL (spurious) |

---

## Metrics reference

### Coverage

```
coverage = matched / total_xbrl_facts_in_scope
```

Measures what fraction of the ground truth facts the PDF pipeline recovered.
Reported per statement and overall.

### Value accuracy tiers

For each matched pair:

```
pct_error = abs(pdf_value - xbrl_value) / abs(xbrl_value) * 100
```

| Tier        | Threshold          |
| ----------- | ------------------ |
| Exact match | `pct_error == 0`   |
| Within 1%   | `pct_error <= 1.0` |
| Within 5%   | `pct_error <= 5.0` |

### Precision / Recall / F1

```
precision = matched / (matched + spurious)
recall    = matched / (matched + missed)
F1        = 2 × precision × recall / (precision + recall)
```

Reported per statement and overall.

### Match tier breakdown

```
tier1_rate = tier1_matches / matched
tier2_rate = tier2_matches / matched
```

A high Tier 2 rate signals that the PDF pipeline's `concept` field is
unreliable — the reconciler had to fall back to canonical name matching.

---

## Run log

`logs/run_log.jsonl` is appended once per evaluation. Never rewritten.

```json
{
  "ts": "2026-05-19T10:00:00Z",
  "ticker": "AAPL",
  "fiscal_year": 2024,
  "pdf_source": "AAPL_FY2024.facts.json",
  "xbrl_source": "aapl.facts.json",
  "status": "success",
  "elapsed_seconds": 0.34,
  "xbrl_facts_scope": 120,
  "pdf_facts_scope": 115,
  "matched": 98,
  "missed": 22,
  "spurious": 17,
  "tier1_matches": 85,
  "tier2_matches": 13,
  "overall_f1": 0.834,
  "overall_coverage": 0.817,
  "exact_match_rate": 0.714,
  "within_1pct_rate": 0.796,
  "within_5pct_rate": 0.857,
  "output_json": "AAPL_FY2024.evaluation.json",
  "output_diff": "AAPL_FY2024.evaluation.diff.txt",
  "error": null
}
```

Quick queries:

```bash
# Average F1 across all successful runs
jq -s '[.[] | select(.status == "success") | .overall_f1] | add / length' logs/run_log.jsonl

# Filings where coverage dropped below 80%
jq 'select(.overall_coverage < 0.80) | {ticker, fiscal_year, overall_coverage}' logs/run_log.jsonl

# Tier 2 match rate per filing (high = concept field unreliable)
jq '{ticker, fiscal_year, tier2_rate: (.tier2_matches / .matched)}' logs/run_log.jsonl
```

---

## Limitations

- **v1 covers four statement types only.** Note-level facts beyond PPE and all
  segment/dimensional facts are out of scope.
- **Tier 2 matching is best-effort.** Canonical-to-label matching is
  case-insensitive text comparison — it can produce false positives when two
  concepts share similar labels. All Tier 2 matches are flagged in the output
  for manual review.
- **No scale inference.** Both sources must carry explicit scale fields. Missing
  or malformed scale values cause the fact to be skipped with a logged warning.
- **Period matching is fiscal-year-level for durations.** Sub-annual periods
  (quarterly, half-year) are not distinguished in v1.
- **Spurious facts are not penalised by value.** A PDF fact with no XBRL
  counterpart counts as spurious regardless of its value. There is no
  false-positive severity weighting in v1.
- **XBRL `labs.json` is optional.** Tier 2 matching degrades to skipped if
  `labs.json` is not present alongside the XBRL facts file. A warning is logged.

---

## Development

Uses **black** for formatting and **ruff** for linting. All dev commands
run through the project's `.venv` automatically — no manual activation
needed.

```bash
make install     # create .venv, pip install -e ".[dev]"
make format      # black src tests + ruff --fix
make lint        # ruff check src tests + black --check
make test        # pytest -v
make setup-check # smoke test of package layout + CLI
make clean       # remove build artefacts (keeps venv)
make clean-venv  # remove the venv directory itself
```

Each `make` target depends on `install` (via a stamp file), so the venv is
created and dependencies installed on first use and skipped thereafter.

Pre-commit hook (optional, also installed by `make install`):

```yaml
repos:
  - repo: https://github.com/psf/black
    rev: 24.10.0
    hooks: [{ id: black }]
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.7.0
    hooks: [{ id: ruff, args: [--fix] }]
```

Install it with:

```bash
.venv/bin/pre-commit install
```
