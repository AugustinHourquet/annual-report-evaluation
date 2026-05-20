"""Adapter: pdf-extraction JSON output → List[FinancialFact].

The PDF pipeline emits a structured JSON with an `entity`, `filing`,
`periods` dict, and a `facts` array. Each fact carries:

    canonical, concept, label, value, unit, scale, period, statement, page

We normalise value x scale to plain dollars, resolve the period key
to a fiscal_year + period_type + period_end triple, and emit canonical
FinancialFact records.

A fact is *in scope* when its `statement` is one of the four v1 statements.
Out-of-scope facts are dropped silently (the PDF pipeline routinely emits
narrative-text facts and other notes we don't evaluate in v1).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..schema import KNOWN_STATEMENTS, FinancialFact
from ..utils import normalise_pdf_value

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PDFExtractionInput:
    """Everything we read from a pdf-extraction file, plus the in-scope facts."""

    path: Path
    entity_name: str | None
    ticker: str | None
    cik: str | None
    reporting_currency: str | None
    accounting_standard: str | None
    fiscal_year: int
    period_end: str
    facts: list[FinancialFact]
    n_skipped: int  # facts dropped because they were out of scope or malformed


def load_pdf_facts(path: str | Path) -> PDFExtractionInput:
    """Load a pdf-extraction *.facts.json file and convert it to canonical form.

    Raises:
        FileNotFoundError: if `path` does not exist.
        ValueError: if the file is missing required top-level keys.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"PDF facts file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        payload: dict[str, Any] = json.load(f)

    # ----- metadata -----
    entity = payload.get("entity") or {}
    filing = payload.get("filing") or {}
    periods = payload.get("periods") or {}
    raw_facts = payload.get("facts") or []

    if "fiscal_year" not in filing or "period_end" not in filing:
        raise ValueError(f"PDF JSON missing required filing.fiscal_year/period_end: {path}")

    in_scope: list[FinancialFact] = []
    n_skipped = 0
    seen: set[tuple[str, str, str, str]] = set()  # de-dup key

    for raw in raw_facts:
        try:
            fact = _convert_fact(raw, periods, entity, filing, path)
        except _SkipFact as e:
            n_skipped += 1
            logger.debug("Skipping PDF fact in %s: %s", path.name, e)
            continue

        if fact.statement not in KNOWN_STATEMENTS:
            n_skipped += 1
            continue

        # de-dup: occasionally the PDF pipeline emits the same concept+period twice
        key = (fact.concept, fact.statement, fact.period_end, fact.period_type)
        if key in seen:
            logger.debug("Duplicate PDF fact dropped: %s", key)
            n_skipped += 1
            continue
        seen.add(key)

        in_scope.append(fact)

    return PDFExtractionInput(
        path=path,
        entity_name=entity.get("name"),
        ticker=entity.get("ticker"),
        cik=entity.get("cik"),
        reporting_currency=entity.get("reporting_currency"),
        accounting_standard=entity.get("accounting_standard"),
        fiscal_year=int(filing["fiscal_year"]),
        period_end=str(filing["period_end"]),
        facts=in_scope,
        n_skipped=n_skipped,
    )


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


class _SkipFact(Exception):
    """Raised internally to drop a malformed fact with a logged reason."""


def _convert_fact(
    raw: dict[str, Any],
    periods: dict[str, Any],
    entity: dict[str, Any],
    filing: dict[str, Any],
    path: Path,
) -> FinancialFact:
    """Turn one raw pdf-extraction fact dict into a canonical FinancialFact."""
    for required in ("concept", "value", "scale", "period", "statement"):
        if required not in raw or raw[required] is None:
            raise _SkipFact(f"missing required field {required!r} in {raw!r}")

    try:
        absolute = normalise_pdf_value(raw["value"], raw["scale"])
    except (ValueError, TypeError) as e:
        raise _SkipFact(f"could not normalise value/scale: {e}") from e

    period_key = raw["period"]
    if isinstance(period_key, dict):
        period_obj = period_key
    else:
        period_obj = periods.get(period_key)
        if period_obj is None:
            raise _SkipFact(f"period key {period_key!r} not found in periods dict")

    period_type = period_obj.get("type")
    if period_type == "duration":
        period_end = period_obj.get("end")
    elif period_type == "instant":
        period_end = period_obj.get("date")
    else:
        raise _SkipFact(f"unknown period type {period_type!r} for {period_key}")

    if period_end is None:
        raise _SkipFact(f"period {period_key!r} has no end/date")

    # Fiscal year: take from the filing, since pdf-extraction reports it there.
    # (Sub-annual periods aren't supported in v1.)
    fiscal_year = int(filing["fiscal_year"])

    unit = raw.get("unit") or entity.get("reporting_currency") or "USD"

    return FinancialFact(
        canonical=raw.get("canonical"),
        concept=str(raw["concept"]),
        label=str(raw.get("label") or raw.get("canonical") or raw["concept"]),
        absolute_value=absolute,
        unit=str(unit),
        period_type=period_type,
        fiscal_year=fiscal_year,
        period_end=str(period_end),
        statement=str(raw["statement"]),
        source="pdf",
        match_tier=None,
    )
