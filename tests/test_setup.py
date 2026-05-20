"""Smoke test: the package imports cleanly and the CLI is wired correctly."""

from __future__ import annotations


def test_package_imports() -> None:
    import annual_report_evaluation as are

    assert are.__version__
    # Public surface
    assert hasattr(are, "FinancialFact")
    assert hasattr(are, "MatchedPair")
    assert hasattr(are, "ReconciliationResult")
    assert hasattr(are, "Scores")
    assert hasattr(are, "EvaluationReport")
    assert hasattr(are, "load_pdf_facts")
    assert hasattr(are, "load_xbrl_facts")
    assert hasattr(are, "reconcile")
    assert hasattr(are, "score")
    assert hasattr(are, "build_report")


def test_cli_main_callable() -> None:
    from annual_report_evaluation.cli import main

    assert callable(main)


def test_cli_help_does_not_crash() -> None:
    import contextlib
    import io

    from annual_report_evaluation.cli import main

    buf = io.StringIO()
    with contextlib.suppress(SystemExit), contextlib.redirect_stdout(buf):
        main(["--help"])
    out = buf.getvalue()
    assert "evaluate-report" in out
    assert "--pdf" in out
    assert "--xbrl" in out
    assert "--dry-run" in out


def test_module_entry_point() -> None:
    # __main__ should exist and be importable.
    import importlib

    importlib.import_module("annual_report_evaluation.__main__")
