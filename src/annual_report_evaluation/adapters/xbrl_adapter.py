"""Adapter: xbrl-extraction JSON output → List[FinancialFact].

The XBRL pipeline emits a `filing` block, `periods` dict (opaque keys like
"c-1"), `units` dict, and a `facts` array. Each fact carries:

    concept, value, unit, period, decimals, scale, dimensions

Critically: there is no `statement` field. We derive it from the concept name
via utils.concept_to_statement, which is a best-effort classification.

A fact is *in scope* when its `dimensions` field is empty/null
(i.e. the primary statement value, not a segment or class breakdown).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..schema import FinancialFact
from ..utils import concept_to_statement, normalise_xbrl_value

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class XBRLExtractionInput:
    """Everything we read from an xbrl-extraction file, plus in-scope facts."""

    path: Path
    fiscal_year: int
    period_end: str
    facts: list[FinancialFact]
    labels: dict[str, list[str]] = field(default_factory=dict)  # concept -> all label variants
    n_skipped_dimensional: int = 0
    n_skipped_malformed: int = 0


# --------------------------------------------------------------------------
# Public loaders
# --------------------------------------------------------------------------


def load_xbrl_facts(path: str | Path, labs_path: str | Path | None = None) -> XBRLExtractionInput:
    """Load an xbrl-extraction *.facts.json file and convert it to canonical form.

    Args:
        path: path to the xbrl-extraction facts JSON.
        labs_path: optional explicit path to a labs.json file. If None, the
            adapter looks for `labs.json` in the same directory as `path`.

    Raises:
        FileNotFoundError: if `path` does not exist.
        ValueError: if the file is missing required top-level keys.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"XBRL facts file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        payload: dict[str, Any] = json.load(f)

    filing = payload.get("filing") or {}
    periods = payload.get("periods") or {}
    raw_facts = payload.get("facts") or []

    if "fiscal_year" not in filing or "period_end" not in filing:
        raise ValueError(f"XBRL JSON missing required filing.fiscal_year/period_end: {path}")

    labels = _resolve_labels(path, labs_path)

    in_scope: list[FinancialFact] = []
    n_dim = 0
    n_bad = 0
    seen: set[tuple[str, str, str]] = set()

    for raw in raw_facts:
        dims = raw.get("dimensions") or {}
        if dims:  # any non-empty dimensions ⇒ disaggregated, skip for v1
            n_dim += 1
            continue

        try:
            fact = _convert_fact(raw, periods, filing, labels)
        except _SkipFact as e:
            logger.debug("Skipping XBRL fact in %s: %s", path.name, e)
            n_bad += 1
            continue

        key = (fact.concept, fact.period_end, fact.period_type)
        if key in seen:
            logger.debug("Duplicate XBRL fact dropped: %s", key)
            n_bad += 1
            continue
        seen.add(key)

        in_scope.append(fact)

    return XBRLExtractionInput(
        path=path,
        fiscal_year=int(filing["fiscal_year"]),
        period_end=str(filing["period_end"]),
        facts=in_scope,
        labels=labels,
        n_skipped_dimensional=n_dim,
        n_skipped_malformed=n_bad,
    )


def load_labels(path: str | Path) -> dict[str, list[str]]:
    """Load a labs.json file. Returns concept → list of all label variants.

    The file format isn't strictly fixed, so this loader is defensive. It
    accepts any of these shapes per concept:

        "us-gaap:X": "Label string"
        "us-gaap:X": ["Label", "Total label"]
        "us-gaap:X": {"label": "...", "totalLabel": "..."}
        "us-gaap:X": {"http://...label": "...", "http://...totalLabel": "..."}

    All non-empty string values found are collected so that Tier 2 matching
    can try each variant.
    """
    path = Path(path)
    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    if not isinstance(payload, dict):
        logger.warning("labs.json at %s is not a JSON object; ignoring", path)
        return {}

    out: dict[str, list[str]] = {}
    for concept, value in payload.items():
        variants = _extract_all_labels(value)
        if variants:
            out[concept] = variants
    return out


# --------------------------------------------------------------------------
# Internals
# --------------------------------------------------------------------------


class _SkipFact(Exception):
    """Raised internally to drop a malformed XBRL fact."""


def _resolve_labels(facts_path: Path, labs_path: str | Path | None) -> dict[str, list[str]]:
    """Find labs.json next to the facts file (or use the explicit path), if any."""
    if labs_path is not None:
        return load_labels(labs_path)

    candidate = facts_path.parent / "labs.json"
    if candidate.exists():
        return load_labels(candidate)

    # Also try replacing `.facts.json` suffix with `.labs.json`
    if facts_path.name.endswith(".facts.json"):
        alt = facts_path.with_name(facts_path.name.removesuffix(".facts.json") + ".labs.json")
        if alt.exists():
            return load_labels(alt)

    logger.info("No labs.json found alongside %s; Tier 2 matching disabled.", facts_path.name)
    return {}


def _extract_all_labels(value: Any) -> list[str]:
    """Collect every non-empty string label found in one labs.json value.

    Returns a deduplicated list in the order: prefer 'label' over 'totalLabel',
    then any other keys. For list/string values, the natural order is preserved.
    """
    found: list[str] = []

    def _add(s: Any) -> None:
        if isinstance(s, str):
            s = s.strip()
            if s and s not in found:
                found.append(s)

    if isinstance(value, str):
        _add(value)
    elif isinstance(value, list):
        for item in value:
            _add(item)
    elif isinstance(value, dict):
        # Prefer 'label' first (shorter, more likely to match canonical),
        # then 'totalLabel', then everything else.
        label_keys = [k for k in value if "label" in k and "totalLabel" not in k]
        total_keys = [k for k in value if "totalLabel" in k]
        other_keys = [k for k in value if k not in label_keys and k not in total_keys]
        for k in label_keys + total_keys + other_keys:
            _add(value[k])
    return found


def _convert_fact(
    raw: dict[str, Any],
    periods: dict[str, Any],
    filing: dict[str, Any],
    labels: dict[str, list[str]],
) -> FinancialFact:
    """Turn one raw xbrl-extraction fact dict into a canonical FinancialFact."""
    for required in ("concept", "value", "scale", "period"):
        if required not in raw:
            raise _SkipFact(f"missing required field {required!r}")

    try:
        absolute = normalise_xbrl_value(raw["value"], raw["scale"])
    except (ValueError, TypeError) as e:
        raise _SkipFact(f"could not normalise value/scale: {e}") from e

    period_key = raw["period"]
    period_obj = periods.get(period_key)
    if period_obj is None:
        raise _SkipFact(f"period key {period_key!r} not found in periods dict")

    period_type = period_obj.get("type")
    if period_type == "duration":
        period_end = period_obj.get("end")
        fy_source = period_end
    elif period_type == "instant":
        period_end = period_obj.get("date")
        fy_source = period_end
    else:
        raise _SkipFact(f"unknown period type {period_type!r}")

    if period_end is None:
        raise _SkipFact(f"period {period_key!r} has no end/date")

    try:
        fiscal_year = int(fy_source[:4])
    except (TypeError, ValueError) as e:
        raise _SkipFact(f"could not parse fiscal year from {fy_source!r}") from e

    concept = str(raw["concept"])
    unit_key = str(raw.get("unit") or "")
    unit = unit_key.upper() if unit_key else "USD"
    if unit.lower() in {"usd", "iso4217:usd"}:
        unit = "USD"

    statement = concept_to_statement(concept)
    variants = labels.get(concept, [])
    display_label = variants[0] if variants else concept

    return FinancialFact(
        canonical=None,  # XBRL has no canonical
        concept=concept,
        label=display_label,
        absolute_value=absolute,
        unit=unit,
        period_type=period_type,
        fiscal_year=fiscal_year,
        period_end=str(period_end),
        statement=statement,
        source="xbrl",
        match_tier=None,
    )
