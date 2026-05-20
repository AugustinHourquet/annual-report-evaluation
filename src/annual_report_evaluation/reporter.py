"""Writers for the two evaluation outputs:

    *.evaluation.json    structured, machine-readable
    *.evaluation.diff.txt  human-scannable per-statement diff

The JSON report is the authoritative output; the diff text is purely for
human review.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .schema import (
    KNOWN_STATEMENTS,
    EvaluationMeta,
    EvaluationReport,
    EvaluationSummary,
    FactReportEntry,
    FinancialFact,
    MatchedPair,
    ReconciliationResult,
    Scores,
)

# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------


def build_report(
    *,
    ticker: str | None,
    fiscal_year: int,
    period_end: str,
    pdf_source: str,
    xbrl_source: str,
    result: ReconciliationResult,
    scores: Scores,
    evaluated_at: str | None = None,
) -> EvaluationReport:
    """Assemble a complete EvaluationReport model from the partitioned sets."""
    if evaluated_at is None:
        evaluated_at = (
            datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        )

    meta = EvaluationMeta(
        ticker=ticker,
        fiscal_year=fiscal_year,
        period_end=period_end,
        pdf_source=pdf_source,
        xbrl_source=xbrl_source,
        evaluated_at=evaluated_at,
        scope=list(KNOWN_STATEMENTS),
    )

    tier1 = sum(1 for p in result.matched if p.match_tier == 1)
    tier2 = sum(1 for p in result.matched if p.match_tier == 2)

    summary = EvaluationSummary(
        xbrl_facts_in_scope=len(result.matched) + len(result.missed),
        pdf_facts_in_scope=len(result.matched) + len(result.spurious),
        matched=len(result.matched),
        missed=len(result.missed),
        spurious=len(result.spurious),
        tier1_matches=tier1,
        tier2_matches=tier2,
    )

    facts = _build_fact_entries(result)

    return EvaluationReport(meta=meta, summary=summary, scores=scores, facts=facts)


def write_json_report(report: EvaluationReport, out_dir: str | Path, ticker: str | None) -> Path:
    """Write the JSON report; return the written path."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tk = ticker or "UNKNOWN"
    fname = f"{tk}_FY{report.meta.fiscal_year}.evaluation.json"
    path = out_dir / fname
    with path.open("w", encoding="utf-8") as f:
        json.dump(report.model_dump(mode="json"), f, indent=2, ensure_ascii=False)
        f.write("\n")
    return path


def write_diff_report(
    report: EvaluationReport,
    result: ReconciliationResult,
    out_dir: str | Path,
    ticker: str | None,
) -> Path:
    """Write the human-readable diff text; return the written path."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tk = ticker or "UNKNOWN"
    fname = f"{tk}_FY{report.meta.fiscal_year}.evaluation.diff.txt"
    path = out_dir / fname
    with path.open("w", encoding="utf-8") as f:
        f.write(_render_diff(report, result, tk))
    return path


# --------------------------------------------------------------------------
# Internals
# --------------------------------------------------------------------------


def _build_fact_entries(result: ReconciliationResult) -> list[FactReportEntry]:
    """Build the flat `facts` array combining matched / missed / spurious rows."""
    entries: list[FactReportEntry] = []

    for pair in result.matched:
        entries.append(
            FactReportEntry(
                canonical=pair.pdf_fact.canonical,
                concept=pair.pdf_fact.concept,
                statement=pair.statement,
                status="matched",
                match_tier=pair.match_tier,
                pdf_value=pair.pdf_fact.absolute_value,
                xbrl_value=pair.xbrl_fact.absolute_value,
                absolute_error=pair.absolute_error,
                pct_error=pair.pct_error,
                exact_match=pair.exact_match,
                within_1pct=pair.within_1pct,
                within_5pct=pair.within_5pct,
            )
        )

    for f in result.missed:
        entries.append(
            FactReportEntry(
                canonical=None,
                concept=f.concept,
                statement=f.statement,
                status="missed",
                match_tier=None,
                pdf_value=None,
                xbrl_value=f.absolute_value,
                absolute_error=None,
                pct_error=None,
                exact_match=None,
                within_1pct=None,
                within_5pct=None,
            )
        )

    for f in result.spurious:
        entries.append(
            FactReportEntry(
                canonical=f.canonical,
                concept=f.concept,
                statement=f.statement,
                status="spurious",
                match_tier=None,
                pdf_value=f.absolute_value,
                xbrl_value=None,
                absolute_error=None,
                pct_error=None,
                exact_match=None,
                within_1pct=None,
                within_5pct=None,
            )
        )

    return entries


# ---- diff rendering --------------------------------------------------------

_STATEMENT_HEADERS = {
    "IncomeStatement": "INCOME STATEMENT",
    "BalanceSheet": "BALANCE SHEET",
    "CashFlow": "CASH FLOW STATEMENT",
    "Note_PPE": "PPE NOTE",
}


def _render_diff(report: EvaluationReport, result: ReconciliationResult, ticker: str) -> str:
    lines: list[str] = []
    bar = "═" * 60
    sub = "─" * 60

    lines.append(bar)
    lines.append(f"ANNUAL REPORT EVALUATION — {ticker} FY{report.meta.fiscal_year}")
    lines.append(f"Evaluated: {report.meta.evaluated_at}")
    lines.append(bar)
    lines.append("")
    lines.append("OVERALL")

    s = report.scores.overall
    summary = report.summary
    total_xbrl = summary.matched + summary.missed
    lines.append(
        f"  Coverage:           {s.coverage:6.1%}  "
        f"({summary.matched} / {total_xbrl} XBRL facts matched)"
    )
    lines.append(f"  Precision:          {s.precision:6.1%}")
    lines.append(f"  Recall:             {s.recall:6.1%}")
    lines.append(f"  F1:                 {s.f1:6.1%}")
    lines.append(f"  Exact match:        {s.exact_match_rate:6.1%}  of matched pairs")
    lines.append(f"  Within 1%:          {s.within_1pct_rate:6.1%}")
    lines.append(f"  Within 5%:          {s.within_5pct_rate:6.1%}")
    if summary.matched > 0:
        t1_rate = summary.tier1_matches / summary.matched
        t2_rate = summary.tier2_matches / summary.matched
        lines.append(f"  Tier 1 (concept):   {t1_rate:6.1%}  of matches")
        lines.append(f"  Tier 2 (canonical): {t2_rate:6.1%}  of matches")
    lines.append("")

    # Group facts by statement using the report.facts array
    by_statement: dict[str, list[FactReportEntry]] = {}
    for entry in report.facts:
        by_statement.setdefault(entry.statement, []).append(entry)

    for statement in KNOWN_STATEMENTS:
        rows = by_statement.get(statement, [])
        if not rows:
            continue
        header = _STATEMENT_HEADERS.get(statement, statement.upper())
        lines.append(sub)
        lines.append(header)
        lines.append(sub)
        for row in rows:
            lines.append(_render_fact_row(row))
        lines.append("")

    # If there are facts in unmapped/Unknown statements, emit them at the end.
    extras = [s for s in by_statement if s not in KNOWN_STATEMENTS]
    for statement in sorted(extras):
        rows = by_statement.get(statement, [])
        if not rows:
            continue
        lines.append(sub)
        lines.append(f"OTHER ({statement})")
        lines.append(sub)
        for row in rows:
            lines.append(_render_fact_row(row))
        lines.append("")

    return "\n".join(lines)


def _render_fact_row(row: FactReportEntry) -> str:
    """One line of the diff report."""
    marker = _row_marker(row)
    name = row.canonical or row.concept
    name = (name[:38]).ljust(38)

    if row.status == "matched":
        pdf = f"${row.pdf_value:>20,.0f}" if row.pdf_value is not None else "—"
        xbrl = f"${row.xbrl_value:>20,.0f}" if row.xbrl_value is not None else "—"
        if row.pct_error is None:
            diff = "  n/a"
        else:
            diff = f"{row.pct_error:6.2f}%"
        return f"  {marker}  {name}  PDF: {pdf}   XBRL: {xbrl}   diff: {diff}"

    if row.status == "missed":
        xbrl = f"${row.xbrl_value:>20,.0f}" if row.xbrl_value is not None else "—"
        return f"  {marker}  {name}  PDF: {'—':>21}   XBRL: {xbrl}"

    # spurious
    pdf = f"${row.pdf_value:>20,.0f}" if row.pdf_value is not None else "—"
    return f"  {marker}  {name}  PDF: {pdf}   XBRL: {'—':>21}"


def _row_marker(row: FactReportEntry) -> str:
    if row.status == "missed":
        return "[MISS  ✗]"
    if row.status == "spurious":
        return "[EXTRA +]"
    # matched: choose tier based on pct_error
    if row.pct_error is None or row.absolute_error == 0:
        return "[MATCH ✓]"
    if row.pct_error <= 1.0:
        return "[CLOSE ~]"
    if row.pct_error <= 5.0:
        return "[DRIFT !]"
    return "[LARGE ⚠]"


# Keep imports used only for typing happy
_unused: tuple = (FinancialFact, MatchedPair)
