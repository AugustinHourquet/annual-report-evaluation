"""Scoring metrics over a ReconciliationResult.

This module has zero knowledge of the source formats. It consumes only
the matched / missed / spurious partitions and produces ScoreBlocks.
"""

from __future__ import annotations

from collections.abc import Iterable

from .schema import (
    KNOWN_STATEMENTS,
    FinancialFact,
    MatchedPair,
    ReconciliationResult,
    ScoreBlock,
    Scores,
)
from .utils import safe_div


def score(result: ReconciliationResult) -> Scores:
    """Compute overall and per-statement metrics from a reconciliation result.

    Per-statement breakdown uses the matched fact's statement (which comes from
    the PDF pipeline's classification), the XBRL-derived statement for missed
    facts, and the PDF statement for spurious facts.

    Statements with zero total activity (no matched, missed, or spurious) are
    omitted from the by_statement dict. "Unknown" statements are also omitted
    — they appear only in overall scores.
    """
    overall = _compute_block(
        matched=result.matched,
        missed=result.missed,
        spurious=result.spurious,
    )

    by_statement: dict[str, ScoreBlock] = {}
    for statement in KNOWN_STATEMENTS:
        m = [p for p in result.matched if p.statement == statement]
        ms = [f for f in result.missed if f.statement == statement]
        sp = [f for f in result.spurious if f.statement == statement]
        if not (m or ms or sp):
            continue  # no activity for this statement; omit
        by_statement[statement] = _compute_block(matched=m, missed=ms, spurious=sp)

    return Scores(overall=overall, by_statement=by_statement)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _compute_block(
    matched: Iterable[MatchedPair],
    missed: Iterable[FinancialFact],
    spurious: Iterable[FinancialFact],
) -> ScoreBlock:
    matched = list(matched)
    missed = list(missed)
    spurious = list(spurious)

    n_matched = len(matched)
    n_missed = len(missed)
    n_spurious = len(spurious)

    # ---- Coverage ----
    # coverage = matched / total_xbrl_facts_in_scope (= matched + missed)
    total_xbrl = n_matched + n_missed
    coverage = safe_div(n_matched, total_xbrl)

    # ---- Precision / Recall / F1 ----
    precision = safe_div(n_matched, n_matched + n_spurious)
    recall = safe_div(n_matched, n_matched + n_missed)
    f1 = safe_div(2 * precision * recall, precision + recall)

    # ---- Value accuracy tiers ----
    # All three are over the matched-pair denominator. Pairs with xbrl_value == 0
    # cannot compute pct_error; we count them as exact_match if absolute_error == 0,
    # but they don't contribute to within_1pct / within_5pct numerators.
    n_exact = sum(1 for p in matched if p.exact_match)
    n_within_1 = sum(1 for p in matched if p.within_1pct)
    n_within_5 = sum(1 for p in matched if p.within_5pct)

    return ScoreBlock(
        coverage=coverage,
        precision=precision,
        recall=recall,
        f1=f1,
        exact_match_rate=safe_div(n_exact, n_matched),
        within_1pct_rate=safe_div(n_within_1, n_matched),
        within_5pct_rate=safe_div(n_within_5, n_matched),
    )
