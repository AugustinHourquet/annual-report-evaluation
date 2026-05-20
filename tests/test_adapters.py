"""Tests for the PDF and XBRL adapters."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from annual_report_evaluation.adapters import (
    load_labels,
    load_pdf_facts,
    load_xbrl_facts,
)
from annual_report_evaluation.schema import FinancialFact
from annual_report_evaluation.utils import (
    concept_to_statement,
    normalise_pdf_value,
    normalise_xbrl_value,
    period_overlap,
)

FIXTURES = Path(__file__).parent / "fixtures"
PDF_FX = FIXTURES / "sample_pdf.facts.json"
XBRL_FX = FIXTURES / "sample_xbrl.facts.json"
LABS_FX = FIXTURES / "sample_xbrl.labs.json"


# --------------------------------------------------------------------------
# pure utils
# --------------------------------------------------------------------------


def test_pdf_scale_millions() -> None:
    assert normalise_pdf_value(391_035, "millions") == 391_035_000_000


def test_pdf_scale_thousands() -> None:
    assert normalise_pdf_value(391_035_000, "thousands") == 391_035_000_000


def test_pdf_scale_actual() -> None:
    assert normalise_pdf_value(1234, "actual") == 1234


def test_pdf_scale_billions() -> None:
    assert normalise_pdf_value(391, "billions") == 391_000_000_000


def test_pdf_scale_unknown_raises() -> None:
    with pytest.raises(ValueError):
        normalise_pdf_value(1, "bazillions")


def test_xbrl_scale_millions() -> None:
    assert normalise_xbrl_value(391_035, "6") == 391_035_000_000


def test_xbrl_scale_zero() -> None:
    assert normalise_xbrl_value(1234, "0") == 1234


def test_xbrl_scale_malformed_raises() -> None:
    with pytest.raises(ValueError):
        normalise_xbrl_value(1, "abc")


def test_period_overlap_same_duration() -> None:
    a = _ff(period_type="duration", fiscal_year=2024, period_end="2024-09-28")
    b = _ff(period_type="duration", fiscal_year=2024, period_end="2024-09-28")
    assert period_overlap(a, b) is True


def test_period_overlap_different_year_duration() -> None:
    a = _ff(period_type="duration", fiscal_year=2023, period_end="2023-09-30")
    b = _ff(period_type="duration", fiscal_year=2024, period_end="2024-09-28")
    assert period_overlap(a, b) is False


def test_period_overlap_instant_match() -> None:
    a = _ff(period_type="instant", fiscal_year=2024, period_end="2024-09-28")
    b = _ff(period_type="instant", fiscal_year=2024, period_end="2024-09-28")
    assert period_overlap(a, b) is True


def test_period_overlap_instant_mismatch() -> None:
    a = _ff(period_type="instant", fiscal_year=2024, period_end="2024-09-28")
    b = _ff(period_type="instant", fiscal_year=2024, period_end="2024-09-30")
    assert period_overlap(a, b) is False


def test_period_overlap_mixed_types() -> None:
    a = _ff(period_type="instant", fiscal_year=2024, period_end="2024-09-28")
    b = _ff(period_type="duration", fiscal_year=2024, period_end="2024-09-28")
    assert period_overlap(a, b) is False


def test_concept_to_statement_known() -> None:
    assert concept_to_statement("us-gaap:Revenues") == "IncomeStatement"
    assert concept_to_statement("us-gaap:Assets") == "BalanceSheet"
    assert concept_to_statement("us-gaap:NetCashProvidedByUsedInOperatingActivities") == "CashFlow"
    assert concept_to_statement("us-gaap:PropertyPlantAndEquipmentGross") == "Note_PPE"


def test_concept_to_statement_pattern_fallback() -> None:
    # Anything containing "Asset" should fall through to BalanceSheet via the regex.
    assert concept_to_statement("acme:RandomAssetThing") == "BalanceSheet"


def test_concept_to_statement_unknown() -> None:
    assert concept_to_statement("custom:CompletelyUnclassifiable") == "Unknown"


# --------------------------------------------------------------------------
# pdf_adapter
# --------------------------------------------------------------------------


def test_pdf_adapter_loads_in_scope() -> None:
    out = load_pdf_facts(PDF_FX)
    # 12 facts total in fixture, but the MD&A one is out-of-scope.
    assert len(out.facts) == 11
    assert out.ticker == "AAPL"
    assert out.cik == "0000320193"
    assert out.fiscal_year == 2024
    assert out.period_end == "2024-09-28"
    assert out.n_skipped >= 1  # MD&A fact dropped


def test_pdf_adapter_normalises_values() -> None:
    out = load_pdf_facts(PDF_FX)
    revenue = next(f for f in out.facts if f.concept == "us-gaap:Revenues")
    assert revenue.absolute_value == 391_035_000_000
    assert revenue.statement == "IncomeStatement"
    assert revenue.period_type == "duration"
    assert revenue.source == "pdf"


def test_pdf_adapter_handles_instant_period() -> None:
    out = load_pdf_facts(PDF_FX)
    assets = next(f for f in out.facts if f.concept == "us-gaap:Assets")
    assert assets.period_type == "instant"
    assert assets.period_end == "2024-09-28"


def test_pdf_adapter_filters_out_of_scope_statements() -> None:
    out = load_pdf_facts(PDF_FX)
    for f in out.facts:
        assert f.statement in {"IncomeStatement", "BalanceSheet", "CashFlow", "Note_PPE"}


def test_pdf_adapter_missing_file() -> None:
    with pytest.raises(FileNotFoundError):
        load_pdf_facts("/nonexistent.json")


def test_pdf_adapter_malformed_fact_skipped(tmp_path: Path) -> None:
    payload = {
        "entity": {"ticker": "X"},
        "filing": {"fiscal_year": 2024, "period_end": "2024-12-31"},
        "periods": {"FY": {"type": "duration", "start": "2024-01-01", "end": "2024-12-31"}},
        "facts": [
            {  # missing scale
                "concept": "us-gaap:Revenues",
                "value": 1,
                "period": "FY",
                "statement": "IncomeStatement",
            },
            {  # missing period
                "concept": "us-gaap:Revenues",
                "value": 1,
                "scale": "actual",
                "statement": "IncomeStatement",
            },
            {  # ok
                "concept": "us-gaap:Revenues",
                "value": 100,
                "scale": "millions",
                "period": "FY",
                "statement": "IncomeStatement",
            },
        ],
    }
    p = tmp_path / "x.facts.json"
    p.write_text(json.dumps(payload))
    out = load_pdf_facts(p)
    assert len(out.facts) == 1
    assert out.n_skipped == 2


def test_pdf_adapter_dedups_identical_facts(tmp_path: Path) -> None:
    payload = {
        "entity": {"ticker": "X"},
        "filing": {"fiscal_year": 2024, "period_end": "2024-12-31"},
        "periods": {"FY": {"type": "duration", "start": "2024-01-01", "end": "2024-12-31"}},
        "facts": [
            {
                "concept": "us-gaap:Revenues",
                "value": 100,
                "scale": "millions",
                "period": "FY",
                "statement": "IncomeStatement",
            },
            {  # duplicate concept+statement+period
                "concept": "us-gaap:Revenues",
                "value": 100,
                "scale": "millions",
                "period": "FY",
                "statement": "IncomeStatement",
            },
        ],
    }
    p = tmp_path / "x.facts.json"
    p.write_text(json.dumps(payload))
    out = load_pdf_facts(p)
    assert len(out.facts) == 1


def test_pdf_adapter_filing_missing_keys(tmp_path: Path) -> None:
    payload = {"entity": {"ticker": "X"}, "filing": {}, "facts": []}
    p = tmp_path / "x.facts.json"
    p.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="filing"):
        load_pdf_facts(p)


# --------------------------------------------------------------------------
# xbrl_adapter
# --------------------------------------------------------------------------


def test_xbrl_adapter_loads_in_scope() -> None:
    out = load_xbrl_facts(XBRL_FX)
    # 12 facts in fixture, 1 has dimensions and is filtered.
    assert len(out.facts) == 11
    assert out.n_skipped_dimensional == 1


def test_xbrl_adapter_normalises_values() -> None:
    out = load_xbrl_facts(XBRL_FX)
    revenue = next(f for f in out.facts if f.concept == "us-gaap:Revenues")
    assert revenue.absolute_value == 391_035_000_000


def test_xbrl_adapter_assigns_statement_from_concept() -> None:
    out = load_xbrl_facts(XBRL_FX)
    revenue = next(f for f in out.facts if f.concept == "us-gaap:Revenues")
    assert revenue.statement == "IncomeStatement"
    cash = next(
        f for f in out.facts if f.concept == "us-gaap:CashAndCashEquivalentsAtCarryingValue"
    )
    assert cash.statement == "BalanceSheet"


def test_xbrl_adapter_filters_dimensional_facts() -> None:
    out = load_xbrl_facts(XBRL_FX)
    # No PPE-by-class facts should survive.
    for f in out.facts:
        assert "Member" not in f.concept


def test_xbrl_adapter_period_to_instant_or_duration() -> None:
    out = load_xbrl_facts(XBRL_FX)
    rev = next(f for f in out.facts if f.concept == "us-gaap:Revenues")
    assert rev.period_type == "duration"
    assets = next(f for f in out.facts if f.concept == "us-gaap:Assets")
    assert assets.period_type == "instant"


def test_xbrl_adapter_with_labels() -> None:
    # When labs.json is alongside the facts file, labels populate display_label.
    out = load_xbrl_facts(XBRL_FX)
    cash = next(
        f for f in out.facts if f.concept == "us-gaap:CashAndCashEquivalentsAtCarryingValue"
    )
    # Display label should come from labs.json (not the concept name).
    assert cash.label == "Cash and cash equivalents"


def test_xbrl_adapter_without_labels(tmp_path: Path) -> None:
    payload = json.loads(XBRL_FX.read_text())
    p = tmp_path / "x.facts.json"
    p.write_text(json.dumps(payload))
    out = load_xbrl_facts(p)
    assert out.labels == {}
    for f in out.facts:
        # With no labels, display_label falls back to concept name.
        assert f.label == f.concept


def test_xbrl_adapter_explicit_labs_path(tmp_path: Path) -> None:
    payload = json.loads(XBRL_FX.read_text())
    p = tmp_path / "renamed.facts.json"
    p.write_text(json.dumps(payload))
    out = load_xbrl_facts(p, labs_path=LABS_FX)
    assert "us-gaap:CashAndCashEquivalentsAtCarryingValue" in out.labels


# --------------------------------------------------------------------------
# load_labels schema variants
# --------------------------------------------------------------------------


def test_load_labels_string_form(tmp_path: Path) -> None:
    p = tmp_path / "labs.json"
    p.write_text(json.dumps({"us-gaap:X": "Just a label"}))
    out = load_labels(p)
    assert out == {"us-gaap:X": ["Just a label"]}


def test_load_labels_dict_form(tmp_path: Path) -> None:
    p = tmp_path / "labs.json"
    p.write_text(json.dumps({"us-gaap:X": {"label": "Short", "totalLabel": "Total long"}}))
    out = load_labels(p)
    # 'label' should appear before 'totalLabel' (preferred).
    assert out["us-gaap:X"][0] == "Short"
    assert "Total long" in out["us-gaap:X"]


def test_load_labels_list_form(tmp_path: Path) -> None:
    p = tmp_path / "labs.json"
    p.write_text(json.dumps({"us-gaap:X": ["A", "B", "A"]}))  # dedup
    out = load_labels(p)
    assert out == {"us-gaap:X": ["A", "B"]}


def test_load_labels_missing_file_returns_empty(tmp_path: Path) -> None:
    out = load_labels(tmp_path / "nope.json")
    assert out == {}


def test_load_labels_full_uri_role_keys(tmp_path: Path) -> None:
    p = tmp_path / "labs.json"
    p.write_text(
        json.dumps(
            {
                "us-gaap:X": {
                    "http://www.xbrl.org/2003/role/label": "Short",
                    "http://www.xbrl.org/2003/role/totalLabel": "Total long",
                }
            }
        )
    )
    out = load_labels(p)
    assert "Short" in out["us-gaap:X"]
    assert "Total long" in out["us-gaap:X"]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _ff(**overrides: object) -> FinancialFact:
    """Build a minimal FinancialFact for unit-test use."""
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
