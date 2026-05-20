"""annual-report-evaluation: scoring an LLM PDF pipeline against XBRL ground truth."""

from __future__ import annotations

__version__ = "0.1.0"

from .adapters import load_pdf_facts, load_xbrl_facts
from .reconciler import reconcile
from .reporter import build_report, write_diff_report, write_json_report
from .schema import (
    EvaluationReport,
    FinancialFact,
    MatchedPair,
    ReconciliationResult,
    ScoreBlock,
    Scores,
)
from .scorer import score

__all__ = [
    "EvaluationReport",
    "FinancialFact",
    "MatchedPair",
    "ReconciliationResult",
    "ScoreBlock",
    "Scores",
    "__version__",
    "build_report",
    "load_pdf_facts",
    "load_xbrl_facts",
    "reconcile",
    "score",
    "write_diff_report",
    "write_json_report",
]
