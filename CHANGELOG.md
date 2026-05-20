# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- **Makefile is now cross-platform.** The same `Makefile` works on Linux,
  macOS, and Windows (with GNU Make installed). On Windows it auto-detects
  via `$(OS)` and uses `.venv\Scripts\python.exe` instead of
  `.venv/bin/python`, defaults to `python` instead of `python3`, and avoids
  Unix-only utilities like `touch`, `tail`, `grep`, and `rm -rf` by routing
  them through a small `scripts/dev.py` helper.
- **Development workflow now uses a project-local virtualenv at `.venv/`.**
  The Makefile bootstraps it automatically — `make install` creates the
  venv (if missing) and installs the package in editable mode with dev
  dependencies. All other `make` targets (`test`, `lint`, `format`,
  `evaluate`, `evaluate-batch`, `setup-check`) run through the venv's
  Python.
- **`pdf-extraction` and `xbrl-extraction` are now an optional `[upstream]`
  extra** rather than required runtime dependencies. The evaluation layer
  never imports them — it only reads the JSON files they produce. This makes
  `pip install -e ".[dev]"` work in a fresh venv without needing the
  unreleased upstream packages on disk. Install them with
  `make install-upstream` (or `pip install -e ".[upstream]"`) when you want
  to regenerate input JSONs.

### Added
- `scripts/dev.py` — small cross-platform helper for `touch`, `clean`,
  `clean-venv`, `log-tail`, and `log-failures` (replaces Unix-specific
  commands).
- `make venv`, `make install-upstream`, and `make clean-venv` targets.
- `VENV`, `PYTHON_BIN`, `PDF_EXTRACTION`, and `XBRL_EXTRACTION` Makefile
  variables for customisation.

## [0.1.0] — 2026-05-19

### Added
- Initial v1 release.
- `pdf_adapter` and `xbrl_adapter` convert upstream JSONs to canonical
  `FinancialFact` records, normalising scale to plain absolute dollars.
- `reconciler` two-tier join (exact concept match, canonical fallback) with
  period-overlap constraint and one-to-one matching guarantee.
- `scorer` computes coverage, precision/recall/F1, and exact / ±1% / ±5%
  value accuracy tiers; per-statement and overall.
- `reporter` writes both `*.evaluation.json` and `*.evaluation.diff.txt`.
- `logger` appends one JSONL record per run to `logs/run_log.jsonl`.
- `evaluate-report` CLI with single-pair, batch, and dry-run modes.
- Test suite covering adapters, reconciler, scorer, reporter, and an
  end-to-end run against synthetic fixtures.

### Scope (v1)
- Income Statement · Balance Sheet · Cash Flow Statement · PPE Note
- Dimensional / segment facts excluded.
- Sub-annual periods not distinguished.
