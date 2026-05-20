"""Canonical data models for the evaluation pipeline.

Everything that flows between adapters → reconciler → scorer → reporter
is one of the models defined here. Pydantic v2.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

# --------------------------------------------------------------------------
# Type aliases
# --------------------------------------------------------------------------

PeriodType = Literal["duration", "instant"]
Source = Literal["pdf", "xbrl"]
Status = Literal["matched", "missed", "spurious"]

# Statements covered by v1. Strings, not a Literal — XBRL facts may carry
# "Unknown" when concept_to_statement cannot classify them.
KNOWN_STATEMENTS: tuple[str, ...] = (
    "IncomeStatement",
    "BalanceSheet",
    "CashFlow",
    "Note_PPE",
)


# --------------------------------------------------------------------------
# FinancialFact — the canonical fact model
# --------------------------------------------------------------------------


class FinancialFact(BaseModel):
    """A single financial fact in canonical form.

    Both pdf_adapter and xbrl_adapter emit lists of these. Values are always
    normalised to plain absolute dollars (no scale, no millions).
    """

    canonical: str | None = None
    concept: str
    label: str
    absolute_value: float
    unit: str
    period_type: PeriodType
    fiscal_year: int
    period_end: str  # ISO date string
    statement: str
    source: Source
    match_tier: int | None = None  # 1, 2, or None if unmatched

    model_config = ConfigDict(frozen=False)


# --------------------------------------------------------------------------
# MatchedPair — a successful reconciliation
# --------------------------------------------------------------------------


class MatchedPair(BaseModel):
    """A PDF fact paired with its XBRL counterpart."""

    pdf_fact: FinancialFact
    xbrl_fact: FinancialFact
    match_tier: int  # 1 = concept match, 2 = canonical fallback

    @computed_field  # type: ignore[prop-decorator]
    @property
    def statement(self) -> str:
        """The PDF pipeline's classification wins for matched pairs."""
        return self.pdf_fact.statement

    @computed_field  # type: ignore[prop-decorator]
    @property
    def absolute_error(self) -> float:
        return abs(self.pdf_fact.absolute_value - self.xbrl_fact.absolute_value)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def pct_error(self) -> float | None:
        """Percent error vs XBRL ground truth, or None if XBRL value is zero."""
        if self.xbrl_fact.absolute_value == 0:
            return None
        return self.absolute_error / abs(self.xbrl_fact.absolute_value) * 100.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def exact_match(self) -> bool:
        return self.absolute_error == 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def within_1pct(self) -> bool:
        return self.pct_error is not None and self.pct_error <= 1.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def within_5pct(self) -> bool:
        return self.pct_error is not None and self.pct_error <= 5.0


# --------------------------------------------------------------------------
# ReconciliationResult — the output of reconciler.reconcile()
# --------------------------------------------------------------------------


class ReconciliationResult(BaseModel):
    """Output of the reconciler: matched / missed / spurious partitions."""

    matched: list[MatchedPair] = Field(default_factory=list)
    missed: list[FinancialFact] = Field(default_factory=list)  # XBRL facts the PDF lost
    spurious: list[FinancialFact] = Field(default_factory=list)  # PDF facts with no XBRL twin


# --------------------------------------------------------------------------
# Scores — output of the scorer
# --------------------------------------------------------------------------


class ScoreBlock(BaseModel):
    """A single set of metrics, either overall or for one statement."""

    coverage: float
    precision: float
    recall: float
    f1: float
    exact_match_rate: float
    within_1pct_rate: float
    within_5pct_rate: float


class Scores(BaseModel):
    """Overall + per-statement metric breakdown."""

    overall: ScoreBlock
    by_statement: dict[str, ScoreBlock]


# --------------------------------------------------------------------------
# Top-level evaluation report (what gets serialised to JSON)
# --------------------------------------------------------------------------


class EvaluationMeta(BaseModel):
    ticker: str | None
    fiscal_year: int
    period_end: str
    pdf_source: str
    xbrl_source: str
    evaluated_at: str  # ISO 8601 UTC
    scope: list[str]


class EvaluationSummary(BaseModel):
    xbrl_facts_in_scope: int
    pdf_facts_in_scope: int
    matched: int
    missed: int
    spurious: int
    tier1_matches: int
    tier2_matches: int


class FactReportEntry(BaseModel):
    """One row in the `facts` array of the JSON report."""

    canonical: str | None
    concept: str
    statement: str
    status: Status
    match_tier: int | None
    pdf_value: float | None
    xbrl_value: float | None
    absolute_error: float | None
    pct_error: float | None
    exact_match: bool | None
    within_1pct: bool | None
    within_5pct: bool | None


class EvaluationReport(BaseModel):
    """The full JSON evaluation report."""

    meta: EvaluationMeta
    summary: EvaluationSummary
    scores: Scores
    facts: list[FactReportEntry]
