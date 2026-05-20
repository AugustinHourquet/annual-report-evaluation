"""Tests for the scorer."""

from __future__ import annotations

import math

from annual_report_evaluation.reconciler import reconcile
from annual_report_evaluation.schema import (
    FinancialFact,
    MatchedPair,
    ReconciliationResult,
)
from annual_report_evaluation.scorer import score

# --------------------------------------------------------------------------
# Overall formula tests
# --------------------------------------------------------------------------


def test_coverage_formula() -> None:
    # 2 matched / (2 matched + 1 missed) = 2/3
    result = _mk_result(
        matched=[_pair(100, 100), _pair(50, 50)],
        missed=[_ff(absolute_value=10, source="xbrl")],
        spurious=[],
    )
    s = score(result)
    assert math.isclose(s.overall.coverage, 2 / 3)


def test_precision_recall_f1() -> None:
    # matched=4, missed=1, spurious=1
    # precision = 4 / (4+1) = 0.8
    # recall    = 4 / (4+1) = 0.8
    # f1        = 0.8
    result = _mk_result(
        matched=[_pair(1, 1), _pair(2, 2), _pair(3, 3), _pair(4, 4)],
        missed=[_ff(absolute_value=99, source="xbrl")],
        spurious=[_ff(absolute_value=88, source="pdf")],
    )
    s = score(result)
    assert math.isclose(s.overall.precision, 0.8)
    assert math.isclose(s.overall.recall, 0.8)
    assert math.isclose(s.overall.f1, 0.8)


def test_exact_match_rate() -> None:
    # 2 exact, 1 not-exact → 2/3
    result = _mk_result(
        matched=[_pair(10, 10), _pair(20, 20), _pair(100, 110)],
        missed=[],
        spurious=[],
    )
    s = score(result)
    assert math.isclose(s.overall.exact_match_rate, 2 / 3)


def test_within_1pct_and_5pct() -> None:
    # pair1: exact          → within_1pct, within_5pct
    # pair2: 0.5% off       → within_1pct, within_5pct
    # pair3: 3% off         → within_5pct only
    # pair4: 10% off        → neither
    result = _mk_result(
        matched=[
            _pair(100, 100),
            _pair(100.5, 100),
            _pair(103, 100),
            _pair(110, 100),
        ],
        missed=[],
        spurious=[],
    )
    s = score(result)
    assert math.isclose(s.overall.within_1pct_rate, 2 / 4)
    assert math.isclose(s.overall.within_5pct_rate, 3 / 4)


def test_zero_xbrl_value_handled() -> None:
    """When XBRL value is zero, pct_error is None; accuracy tiers exclude that pair."""
    pair = _pair(0, 0)  # both zero — exact_match True, pct_error None
    assert pair.exact_match is True
    assert pair.pct_error is None
    result = _mk_result(matched=[pair], missed=[], spurious=[])
    s = score(result)
    assert s.overall.exact_match_rate == 1.0
    assert s.overall.within_1pct_rate == 0.0  # within_1pct is False when pct_error is None
    assert s.overall.within_5pct_rate == 0.0


def test_empty_result_does_not_explode() -> None:
    result = _mk_result(matched=[], missed=[], spurious=[])
    s = score(result)
    assert s.overall.coverage == 0.0
    assert s.overall.precision == 0.0
    assert s.overall.recall == 0.0
    assert s.overall.f1 == 0.0
    assert s.by_statement == {}


# --------------------------------------------------------------------------
# Per-statement breakdown
# --------------------------------------------------------------------------


def test_per_statement_breakdown_only_includes_active_statements() -> None:
    # Only IncomeStatement has activity.
    result = _mk_result(
        matched=[_pair(100, 100, statement="IncomeStatement")],
        missed=[],
        spurious=[],
    )
    s = score(result)
    assert "IncomeStatement" in s.by_statement
    assert "BalanceSheet" not in s.by_statement
    assert "CashFlow" not in s.by_statement
    assert "Note_PPE" not in s.by_statement


def test_per_statement_breakdown_excludes_unknown_statement() -> None:
    result = _mk_result(
        matched=[_pair(100, 100, statement="Unknown")],
        missed=[_ff(absolute_value=10, source="xbrl", statement="Unknown")],
        spurious=[],
    )
    s = score(result)
    # Overall still counts these.
    assert s.overall.coverage == 0.5
    # by_statement omits Unknown.
    assert "Unknown" not in s.by_statement


def test_per_statement_breakdown_correct_numbers() -> None:
    # IS: 2 matched, 1 spurious → P=2/3, R=1.0, F1=0.8
    # BS: 1 matched, 1 missed   → P=1.0, R=0.5, F1=0.667
    result = _mk_result(
        matched=[
            _pair(1, 1, statement="IncomeStatement"),
            _pair(2, 2, statement="IncomeStatement"),
            _pair(3, 3, statement="BalanceSheet"),
        ],
        missed=[_ff(absolute_value=99, source="xbrl", statement="BalanceSheet")],
        spurious=[_ff(absolute_value=88, source="pdf", statement="IncomeStatement")],
    )
    s = score(result)

    is_b = s.by_statement["IncomeStatement"]
    assert math.isclose(is_b.precision, 2 / 3)
    assert math.isclose(is_b.recall, 1.0)

    bs_b = s.by_statement["BalanceSheet"]
    assert math.isclose(bs_b.precision, 1.0)
    assert math.isclose(bs_b.recall, 0.5)


# --------------------------------------------------------------------------
# End-to-end against the fixture (sanity check)
# --------------------------------------------------------------------------


def test_against_full_fixture() -> None:
    """Sanity-check the scorer using the live reconciler + fixture data."""
    from pathlib import Path

    from annual_report_evaluation.adapters import load_pdf_facts, load_xbrl_facts

    fixtures = Path(__file__).parent / "fixtures"
    pdf = load_pdf_facts(fixtures / "sample_pdf.facts.json")
    xbrl = load_xbrl_facts(fixtures / "sample_xbrl.facts.json")
    result = reconcile(pdf.facts, xbrl.facts, labels=xbrl.labels)

    # 10 matched (9 Tier 1 + 1 Tier 2), 1 missed (OpLease), 1 spurious (Hallucinated)
    assert len(result.matched) == 10
    assert len(result.missed) == 1
    assert len(result.spurious) == 1
    tier1 = [p for p in result.matched if p.match_tier == 1]
    tier2 = [p for p in result.matched if p.match_tier == 2]
    assert len(tier1) == 9
    assert len(tier2) == 1
    assert tier2[0].xbrl_fact.concept == "us-gaap:CashAndCashEquivalentsAtCarryingValue"

    s = score(result)
    # coverage = 10/11
    assert math.isclose(s.overall.coverage, 10 / 11, rel_tol=1e-9)
    # precision = recall = 10/11
    assert math.isclose(s.overall.precision, 10 / 11, rel_tol=1e-9)
    assert math.isclose(s.overall.recall, 10 / 11, rel_tol=1e-9)
    # 9 of 10 are exact (R&D is off by $5M)
    assert math.isclose(s.overall.exact_match_rate, 9 / 10)
    # All 10 are within 1% (R&D is ~0.016% off)
    assert math.isclose(s.overall.within_1pct_rate, 1.0)
    assert math.isclose(s.overall.within_5pct_rate, 1.0)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _ff(
    absolute_value: float = 0.0,
    *,
    source: str = "pdf",
    concept: str = "us-gaap:Test",
    statement: str = "IncomeStatement",
    period_type: str = "duration",
    fiscal_year: int = 2024,
    period_end: str = "2024-12-31",
    canonical: str | None = None,
    match_tier: int | None = None,
) -> FinancialFact:
    return FinancialFact(
        canonical=canonical,
        concept=concept,
        label=concept,
        absolute_value=absolute_value,
        unit="USD",
        period_type=period_type,  # type: ignore[arg-type]
        fiscal_year=fiscal_year,
        period_end=period_end,
        statement=statement,
        source=source,  # type: ignore[arg-type]
        match_tier=match_tier,
    )


def _pair(pdf_val: float, xbrl_val: float, statement: str = "IncomeStatement") -> MatchedPair:
    return MatchedPair(
        pdf_fact=_ff(absolute_value=pdf_val, source="pdf", statement=statement, match_tier=1),
        xbrl_fact=_ff(absolute_value=xbrl_val, source="xbrl", statement=statement, match_tier=1),
        match_tier=1,
    )


def _mk_result(
    matched: list[MatchedPair],
    missed: list[FinancialFact],
    spurious: list[FinancialFact],
) -> ReconciliationResult:
    return ReconciliationResult(matched=matched, missed=missed, spurious=spurious)
