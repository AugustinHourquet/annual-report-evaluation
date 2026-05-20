"""Two-tier reconciler.

Inputs are already-canonical FinancialFact lists from the adapters.
The reconciler must NOT import from the adapter modules directly — it
only consumes their output.

Join strategy:

    Tier 1 (concept):    pdf.concept == xbrl.concept, plus period overlap.
    Tier 2 (canonical):  pdf.canonical (lower/stripped) matches an XBRL
                         concept's label (from labs.json), plus period overlap.

A fact can be matched at most once. Any XBRL fact unmatched after both
tiers is "missed". Any PDF fact unmatched after both tiers is "spurious".
"""

from __future__ import annotations

import logging

from .schema import FinancialFact, MatchedPair, ReconciliationResult
from .utils import period_overlap

logger = logging.getLogger(__name__)


def reconcile(
    pdf_facts: list[FinancialFact],
    xbrl_facts: list[FinancialFact],
    labels: dict[str, list[str]] | None = None,
) -> ReconciliationResult:
    """Join PDF facts to XBRL facts in two tiers; partition into matched / missed / spurious.

    Args:
        pdf_facts: canonical FinancialFacts from the PDF adapter (in scope only).
        xbrl_facts: canonical FinancialFacts from the XBRL adapter (in scope only).
        labels: optional dict of concept → list of label variants, used for Tier 2
            matching. When empty or None, Tier 2 is skipped and a warning is logged.

    Returns:
        ReconciliationResult with matched/missed/spurious partitions.
    """
    labels = labels or {}
    matched: list[MatchedPair] = []
    used_pdf_idx: set[int] = set()
    used_xbrl_idx: set[int] = set()

    # ----------------------------------------------------------------------
    # Tier 1: exact concept match
    # ----------------------------------------------------------------------
    pdf_by_concept: dict[str, list[int]] = {}
    for i, fact in enumerate(pdf_facts):
        pdf_by_concept.setdefault(fact.concept, []).append(i)

    for j, x in enumerate(xbrl_facts):
        candidates = pdf_by_concept.get(x.concept, [])
        for i in candidates:
            if i in used_pdf_idx:
                continue
            p = pdf_facts[i]
            if not period_overlap(p, x):
                continue
            p_tagged = _with_tier(p, 1)
            x_tagged = _with_tier(x, 1)
            matched.append(MatchedPair(pdf_fact=p_tagged, xbrl_fact=x_tagged, match_tier=1))
            used_pdf_idx.add(i)
            used_xbrl_idx.add(j)
            break

    # ----------------------------------------------------------------------
    # Tier 2: canonical fallback via labs.json
    # ----------------------------------------------------------------------
    if not labels:
        logger.info("No labels available; Tier 2 matching skipped.")
    else:
        # Build a PDF-canonical index (normalised) over still-unmatched PDF facts.
        pdf_by_canonical: dict[str, list[int]] = {}
        for i, fact in enumerate(pdf_facts):
            if i in used_pdf_idx:
                continue
            if fact.canonical:
                key = _normalise_text(fact.canonical)
                if key:
                    pdf_by_canonical.setdefault(key, []).append(i)

        for j, x in enumerate(xbrl_facts):
            if j in used_xbrl_idx:
                continue
            variants = labels.get(x.concept) or []
            if not variants:
                continue
            # Try every label variant; first one that hits a PDF canonical wins.
            matched_this = False
            for variant in variants:
                key = _normalise_text(variant)
                if not key:
                    continue
                candidates = pdf_by_canonical.get(key, [])
                for i in candidates:
                    if i in used_pdf_idx:
                        continue
                    p = pdf_facts[i]
                    if not period_overlap(p, x):
                        continue
                    p_tagged = _with_tier(p, 2)
                    x_tagged = _with_tier(x, 2)
                    matched.append(MatchedPair(pdf_fact=p_tagged, xbrl_fact=x_tagged, match_tier=2))
                    used_pdf_idx.add(i)
                    used_xbrl_idx.add(j)
                    logger.debug(
                        "Tier 2 match: pdf.canonical=%r ↔ xbrl.concept=%r (via label=%r)",
                        p.canonical,
                        x.concept,
                        variant,
                    )
                    matched_this = True
                    break
                if matched_this:
                    break

    # ----------------------------------------------------------------------
    # Partition the rest
    # ----------------------------------------------------------------------
    missed = [x for j, x in enumerate(xbrl_facts) if j not in used_xbrl_idx]
    spurious = [p for i, p in enumerate(pdf_facts) if i not in used_pdf_idx]

    return ReconciliationResult(matched=matched, missed=missed, spurious=spurious)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _normalise_text(s: str) -> str:
    """Lowercase, strip whitespace and trailing colons — for Tier 2 comparison."""
    return s.strip().rstrip(":").lower()


def _with_tier(fact: FinancialFact, tier: int) -> FinancialFact:
    """Return a copy of `fact` with match_tier set."""
    return fact.model_copy(update={"match_tier": tier})
