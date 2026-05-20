"""Tests for the two-tier reconciler."""

from __future__ import annotations

from annual_report_evaluation.reconciler import reconcile
from annual_report_evaluation.schema import FinancialFact

# --------------------------------------------------------------------------
# Tier 1 — exact concept match
# --------------------------------------------------------------------------


def test_tier1_match_on_same_concept_and_period() -> None:
    pdf = [_ff(concept="us-gaap:Revenues", absolute_value=100.0)]
    xbrl = [_ff(concept="us-gaap:Revenues", absolute_value=100.0, source="xbrl")]
    result = reconcile(pdf, xbrl)
    assert len(result.matched) == 1
    assert result.matched[0].match_tier == 1
    assert result.matched[0].pdf_fact.match_tier == 1
    assert result.matched[0].xbrl_fact.match_tier == 1
    assert not result.missed
    assert not result.spurious


def test_tier1_no_match_when_concept_differs() -> None:
    pdf = [_ff(concept="us-gaap:Revenues")]
    xbrl = [_ff(concept="us-gaap:NetIncomeLoss", source="xbrl")]
    result = reconcile(pdf, xbrl)
    assert not result.matched
    assert len(result.missed) == 1
    assert len(result.spurious) == 1


def test_tier1_no_match_on_period_mismatch_duration() -> None:
    pdf = [_ff(concept="us-gaap:Revenues", fiscal_year=2023)]
    xbrl = [_ff(concept="us-gaap:Revenues", fiscal_year=2024, source="xbrl")]
    result = reconcile(pdf, xbrl)
    assert not result.matched


def test_tier1_no_match_on_period_mismatch_instant() -> None:
    pdf = [_ff(concept="us-gaap:Assets", period_type="instant", period_end="2023-12-31")]
    xbrl = [
        _ff(
            concept="us-gaap:Assets",
            period_type="instant",
            period_end="2024-12-31",
            source="xbrl",
        )
    ]
    result = reconcile(pdf, xbrl)
    assert not result.matched


def test_tier1_no_match_duration_vs_instant() -> None:
    pdf = [_ff(concept="us-gaap:Revenues", period_type="duration")]
    xbrl = [_ff(concept="us-gaap:Revenues", period_type="instant", source="xbrl")]
    result = reconcile(pdf, xbrl)
    assert not result.matched


# --------------------------------------------------------------------------
# Tier 2 — canonical fallback
# --------------------------------------------------------------------------


def test_tier2_canonical_match_via_label() -> None:
    pdf = [
        _ff(
            canonical="Cash and cash equivalents",
            concept="custom:Cash",
            absolute_value=100.0,
        )
    ]
    xbrl = [
        _ff(
            concept="us-gaap:CashAndCashEquivalentsAtCarryingValue",
            absolute_value=100.0,
            source="xbrl",
        )
    ]
    labels = {"us-gaap:CashAndCashEquivalentsAtCarryingValue": ["Cash and cash equivalents"]}
    result = reconcile(pdf, xbrl, labels=labels)
    assert len(result.matched) == 1
    assert result.matched[0].match_tier == 2


def test_tier2_case_and_whitespace_insensitive() -> None:
    pdf = [_ff(canonical="  Cash and Cash Equivalents  ", concept="custom:C")]
    xbrl = [_ff(concept="us-gaap:Cash", source="xbrl")]
    labels = {"us-gaap:Cash": ["cash and cash equivalents:"]}
    result = reconcile(pdf, xbrl, labels=labels)
    assert len(result.matched) == 1
    assert result.matched[0].match_tier == 2


def test_tier2_skipped_when_no_labels() -> None:
    pdf = [_ff(canonical="Cash and cash equivalents", concept="custom:C")]
    xbrl = [_ff(concept="us-gaap:Cash", source="xbrl")]
    result = reconcile(pdf, xbrl)  # no labels
    assert not result.matched
    assert len(result.missed) == 1
    assert len(result.spurious) == 1


def test_tier2_tries_multiple_label_variants() -> None:
    pdf = [_ff(canonical="Total revenues", concept="custom:R")]
    xbrl = [_ff(concept="us-gaap:Revenues", source="xbrl")]
    # First variant won't match; second variant will.
    labels = {"us-gaap:Revenues": ["Revenues", "Total revenues"]}
    result = reconcile(pdf, xbrl, labels=labels)
    assert len(result.matched) == 1
    assert result.matched[0].match_tier == 2


def test_tier2_requires_period_overlap() -> None:
    pdf = [
        _ff(canonical="Cash", concept="custom:C", period_type="instant", period_end="2023-12-31")
    ]
    xbrl = [
        _ff(
            concept="us-gaap:Cash",
            period_type="instant",
            period_end="2024-12-31",
            source="xbrl",
        )
    ]
    labels = {"us-gaap:Cash": ["Cash"]}
    result = reconcile(pdf, xbrl, labels=labels)
    assert not result.matched


def test_tier2_does_not_re_match_tier1_pair() -> None:
    """A PDF fact already matched in Tier 1 cannot be re-used in Tier 2."""
    pdf = [
        _ff(canonical="Cash and cash equivalents", concept="us-gaap:Cash", absolute_value=100.0),
    ]
    xbrl = [
        # First, an exact concept-match XBRL fact (will consume the PDF in Tier 1).
        _ff(concept="us-gaap:Cash", absolute_value=100.0, source="xbrl"),
        # Second, an XBRL fact whose label points at the same PDF canonical.
        _ff(
            concept="us-gaap:OtherCashConcept",
            absolute_value=50.0,
            source="xbrl",
        ),
    ]
    labels = {"us-gaap:OtherCashConcept": ["Cash and cash equivalents"]}
    result = reconcile(pdf, xbrl, labels=labels)
    # Only one match — the PDF fact is consumed in Tier 1.
    assert len(result.matched) == 1
    assert result.matched[0].match_tier == 1
    # The second XBRL fact ends up missed.
    assert len(result.missed) == 1
    assert result.missed[0].concept == "us-gaap:OtherCashConcept"


# --------------------------------------------------------------------------
# Partitioning behaviour
# --------------------------------------------------------------------------


def test_missed_when_xbrl_has_no_pdf_counterpart() -> None:
    pdf: list[FinancialFact] = []
    xbrl = [_ff(concept="us-gaap:Revenues", source="xbrl")]
    result = reconcile(pdf, xbrl)
    assert not result.matched
    assert len(result.missed) == 1
    assert not result.spurious


def test_spurious_when_pdf_has_no_xbrl_counterpart() -> None:
    pdf = [_ff(concept="custom:Hallucinated")]
    xbrl: list[FinancialFact] = []
    result = reconcile(pdf, xbrl)
    assert not result.matched
    assert not result.missed
    assert len(result.spurious) == 1


def test_full_partition_mixed() -> None:
    pdf = [
        _ff(concept="us-gaap:Revenues"),
        _ff(concept="custom:Hallucinated"),
    ]
    xbrl = [
        _ff(concept="us-gaap:Revenues", source="xbrl"),
        _ff(concept="us-gaap:NetIncomeLoss", source="xbrl"),
    ]
    result = reconcile(pdf, xbrl)
    assert len(result.matched) == 1
    assert len(result.missed) == 1
    assert len(result.spurious) == 1


def test_one_to_one_matching_no_double_consume() -> None:
    """A single PDF fact must not be matched to two different XBRL facts."""
    pdf = [_ff(concept="us-gaap:Revenues")]
    xbrl = [
        _ff(concept="us-gaap:Revenues", source="xbrl"),
        _ff(concept="us-gaap:Revenues", source="xbrl"),  # second one shouldn't match
    ]
    result = reconcile(pdf, xbrl)
    assert len(result.matched) == 1
    assert len(result.missed) == 1


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _ff(**overrides: object) -> FinancialFact:
    defaults: dict[str, object] = dict(
        canonical=None,
        concept="us-gaap:Test",
        label="Test",
        absolute_value=0.0,
        unit="USD",
        period_type="duration",
        fiscal_year=2024,
        period_end="2024-12-31",
        statement="IncomeStatement",
        source="pdf",
        match_tier=None,
    )
    defaults.update(overrides)
    return FinancialFact(**defaults)  # type: ignore[arg-type]
