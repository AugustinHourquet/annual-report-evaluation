.PHONY: help install install-upstream format lint test setup-check \
        evaluate evaluate-batch log-tail log-failures clean

# --------------------------------------------------------------------------
# Help
# --------------------------------------------------------------------------

help:
	@echo "Activate your virtualenv first, then use these targets:"
	@echo ""
	@echo "  make install          - editable install with dev deps"
	@echo "  make install-upstream - also install ../pdf-extraction and ../xbrl-extraction"
	@echo "  make format           - run black + ruff --fix"
	@echo "  make lint             - run ruff + black --check"
	@echo "  make test             - run pytest"
	@echo "  make setup-check      - quick smoke test of the package layout"
	@echo "  make evaluate         - single evaluation; pass PDF=... XBRL=..."
	@echo "  make evaluate-batch   - batch evaluation; pass PDF_DIR=... XBRL_DIR=..."
	@echo "  make log-tail         - show last 20 lines of logs/run_log.jsonl"
	@echo "  make log-failures     - show all failure entries from the run log"
	@echo "  make clean            - remove build artefacts (caches, egg-info, etc.)"

# --------------------------------------------------------------------------
# Install
# --------------------------------------------------------------------------

install:
	pip install -e ".[dev]"

# Optional: install the two upstream extraction packages from sibling
# editable sources. Override paths with:
#   make PDF_EXTRACTION=/path/to/pdf-extraction install-upstream
PDF_EXTRACTION  ?= ../pdf-extraction
XBRL_EXTRACTION ?= ../xbrl-extraction
install-upstream: install
	pip install -e "$(PDF_EXTRACTION)[anthropic]" -e "$(XBRL_EXTRACTION)"

# --------------------------------------------------------------------------
# Dev tasks
# --------------------------------------------------------------------------

format:
	black src tests
	ruff check --fix src tests

lint:
	ruff check src tests
	black --check src tests

test:
	pytest -v

setup-check:
	python -c "import annual_report_evaluation as a; print('version:', a.__version__)"
	python -c "from annual_report_evaluation import cli; cli._build_parser(); print('CLI OK')"

# --------------------------------------------------------------------------
# Evaluation targets
# --------------------------------------------------------------------------

evaluate:
	python -m annual_report_evaluation --pdf "$(PDF)" --xbrl "$(XBRL)" --out data/output

evaluate-batch:
	python -m annual_report_evaluation --pdf-dir "$(PDF_DIR)" --xbrl-dir "$(XBRL_DIR)" --out data/output

# --------------------------------------------------------------------------
# Logs
# --------------------------------------------------------------------------

log-tail:
	@python scripts/dev.py log-tail

log-failures:
	@python scripts/dev.py log-failures

# --------------------------------------------------------------------------
# Cleaning
# --------------------------------------------------------------------------

clean:
	@python scripts/dev.py clean
