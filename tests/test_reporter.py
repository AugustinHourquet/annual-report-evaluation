"""Tests for the JSON and diff text report writers."""

from __future__ import annotations

import json
from pathlib import Path

from annual_report_evaluation.reconciler import reconcile
from annual_report_evaluation.reporter import (
    build_report,
    write_diff_report,
    write_json_report,
)
from annual_report_evaluation.schema import (
    FinancialFact,
    MatchedPair,
    ReconciliationResult,
)
from annual_report_evaluation.scorer import score

# --------------------------------------------------------------------------
# build_report — structural correctness
# --------------------------------------------------------------------------


def test_build_report_meta_summary_scores() -> None:
    result = ReconciliationResult(
        matched=[_pair(100, 100)],
        missed=[_ff(absolute_value=50, source="xbrl")],
        spurious=[_ff(absolute_value=25, source="pdf")],
    )
    scores = score(result)
    rep = build_report(
        ticker="AAPL",
        fiscal_year=2024,
        period_end="2024-09-28",
        pdf_source="aapl.pdf.json",
        xbrl_source="aapl.xbrl.json",
        result=result,
        scores=scores,
    )

    assert rep.meta.ticker == "AAPL"
    assert rep.meta.fiscal_year == 2024
    assert rep.meta.period_end == "2024-09-28"
    assert rep.meta.evaluated_at  # populated
    assert "IncomeStatement" in rep.meta.scope

    assert rep.summary.matched == 1
    assert rep.summary.missed == 1
    assert rep.summary.spurious == 1
    assert rep.summary.tier1_matches == 1
    assert rep.summary.tier2_matches == 0
    assert rep.summary.xbrl_facts_in_scope == 2
    assert rep.summary.pdf_facts_in_scope == 2

    assert rep.scores is scores

    # facts array contains one entry per status
    statuses = sorted(e.status for e in rep.facts)
    assert statuses == ["matched", "missed", "spurious"]


def test_build_report_tier_counts() -> None:
    pair_t1 = _pair(100, 100, tier=1)
    pair_t2 = _pair(50, 50, tier=2)
    rep = build_report(
        ticker="X",
        fiscal_year=2024,
        period_end="2024-12-31",
        pdf_source="p.json",
        xbrl_source="x.json",
        result=ReconciliationResult(matched=[pair_t1, pair_t2], missed=[], spurious=[]),
        scores=score(ReconciliationResult(matched=[pair_t1, pair_t2], missed=[], spurious=[])),
    )
    assert rep.summary.tier1_matches == 1
    assert rep.summary.tier2_matches == 1


# --------------------------------------------------------------------------
# JSON writer
# --------------------------------------------------------------------------


def test_write_json_report_filename_pattern(tmp_path: Path) -> None:
    rep = _minimal_report("AAPL", 2024)
    out = write_json_report(rep, tmp_path, "AAPL")
    assert out.name == "AAPL_FY2024.evaluation.json"
    assert out.exists()


def test_write_json_report_valid_json(tmp_path: Path) -> None:
    rep = _minimal_report("AAPL", 2024)
    out = write_json_report(rep, tmp_path, "AAPL")
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["meta"]["ticker"] == "AAPL"
    assert payload["meta"]["fiscal_year"] == 2024
    assert "summary" in payload
    assert "scores" in payload
    assert "facts" in payload


def test_write_json_report_falls_back_to_unknown_ticker(tmp_path: Path) -> None:
    rep = _minimal_report(None, 2024)
    out = write_json_report(rep, tmp_path, None)
    assert out.name == "UNKNOWN_FY2024.evaluation.json"


# --------------------------------------------------------------------------
# Diff text writer
# --------------------------------------------------------------------------


def test_write_diff_report_filename_pattern(tmp_path: Path) -> None:
    rep = _minimal_report("AAPL", 2024)
    result = ReconciliationResult()
    out = write_diff_report(rep, result, tmp_path, "AAPL")
    assert out.name == "AAPL_FY2024.evaluation.diff.txt"


def test_diff_report_contains_overall_scores(tmp_path: Path) -> None:
    result = ReconciliationResult(matched=[_pair(100, 100)], missed=[], spurious=[])
    rep = build_report(
        ticker="X",
        fiscal_year=2024,
        period_end="2024-12-31",
        pdf_source="p",
        xbrl_source="x",
        result=result,
        scores=score(result),
    )
    out = write_diff_report(rep, result, tmp_path, "X")
    text = out.read_text(encoding="utf-8")
    assert "ANNUAL REPORT EVALUATION" in text
    assert "OVERALL" in text
    assert "Coverage:" in text
    assert "Precision:" in text


def test_diff_report_markers(tmp_path: Path) -> None:
    """Each match category should produce the right marker."""
    matched = [
        _pair(100, 100),  # exact → [MATCH ✓]
        _pair(100.5, 100),  # 0.5% off → [CLOSE ~]
        _pair(103, 100),  # 3% off → [DRIFT !]
        _pair(150, 100),  # 50% off → [LARGE ⚠]
    ]
    missed = [_ff(absolute_value=10, source="xbrl")]
    spurious = [_ff(absolute_value=20, source="pdf")]
    result = ReconciliationResult(matched=matched, missed=missed, spurious=spurious)
    rep = build_report(
        ticker="X",
        fiscal_year=2024,
        period_end="2024-12-31",
        pdf_source="p",
        xbrl_source="x",
        result=result,
        scores=score(result),
    )
    out = write_diff_report(rep, result, tmp_path, "X")
    text = out.read_text(encoding="utf-8")
    assert "[MATCH ✓]" in text
    assert "[CLOSE ~]" in text
    assert "[DRIFT !]" in text
    assert "[LARGE ⚠]" in text
    assert "[MISS  ✗]" in text
    assert "[EXTRA +]" in text


def test_diff_report_includes_statement_headers(tmp_path: Path) -> None:
    result = ReconciliationResult(
        matched=[
            _pair(100, 100, statement="IncomeStatement"),
            _pair(200, 200, statement="BalanceSheet"),
            _pair(300, 300, statement="CashFlow"),
            _pair(400, 400, statement="Note_PPE"),
        ],
        missed=[],
        spurious=[],
    )
    rep = build_report(
        ticker="X",
        fiscal_year=2024,
        period_end="2024-12-31",
        pdf_source="p",
        xbrl_source="x",
        result=result,
        scores=score(result),
    )
    out = write_diff_report(rep, result, tmp_path, "X")
    text = out.read_text(encoding="utf-8")
    assert "INCOME STATEMENT" in text
    assert "BALANCE SHEET" in text
    assert "CASH FLOW STATEMENT" in text
    assert "PPE NOTE" in text


# --------------------------------------------------------------------------
# End-to-end: pipeline on the fixture, JSON output round-trips
# --------------------------------------------------------------------------


def test_end_to_end_fixture_writes_both_files(tmp_path: Path) -> None:
    from annual_report_evaluation.adapters import load_pdf_facts, load_xbrl_facts

    fixtures = Path(__file__).parent / "fixtures"
    pdf = load_pdf_facts(fixtures / "sample_pdf.facts.json")
    xbrl = load_xbrl_facts(fixtures / "sample_xbrl.facts.json")
    result = reconcile(pdf.facts, xbrl.facts, labels=xbrl.labels)
    scores = score(result)
    rep = build_report(
        ticker=pdf.ticker,
        fiscal_year=pdf.fiscal_year,
        period_end=pdf.period_end,
        pdf_source="sample_pdf.facts.json",
        xbrl_source="sample_xbrl.facts.json",
        result=result,
        scores=scores,
    )
    json_out = write_json_report(rep, tmp_path, pdf.ticker)
    diff_out = write_diff_report(rep, result, tmp_path, pdf.ticker)

    # Both files exist and have content.
    assert json_out.exists() and json_out.stat().st_size > 0
    assert diff_out.exists() and diff_out.stat().st_size > 0

    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["summary"]["matched"] == 10
    assert payload["summary"]["missed"] == 1
    assert payload["summary"]["spurious"] == 1
    assert payload["summary"]["tier1_matches"] == 9
    assert payload["summary"]["tier2_matches"] == 1


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _ff(
    absolute_value: float = 0.0,
    *,
    source: str = "pdf",
    concept: str = "us-gaap:Test",
    statement: str = "IncomeStatement",
    canonical: str | None = None,
) -> FinancialFact:
    return FinancialFact(
        canonical=canonical,
        concept=concept,
        label=concept,
        absolute_value=absolute_value,
        unit="USD",
        period_type="duration",
        fiscal_year=2024,
        period_end="2024-12-31",
        statement=statement,
        source=source,  # type: ignore[arg-type]
        match_tier=None,
    )


def _pair(
    pdf_val: float, xbrl_val: float, statement: str = "IncomeStatement", tier: int = 1
) -> MatchedPair:
    return MatchedPair(
        pdf_fact=_ff(absolute_value=pdf_val, source="pdf", statement=statement),
        xbrl_fact=_ff(absolute_value=xbrl_val, source="xbrl", statement=statement),
        match_tier=tier,
    )


def _minimal_report(ticker: str | None, fy: int):
    result = ReconciliationResult()
    return build_report(
        ticker=ticker,
        fiscal_year=fy,
        period_end=f"{fy}-12-31",
        pdf_source="p",
        xbrl_source="x",
        result=result,
        scores=score(result),
    )
