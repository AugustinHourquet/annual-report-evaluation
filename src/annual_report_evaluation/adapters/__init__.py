"""Adapters convert upstream JSON outputs into canonical FinancialFact lists.

Each adapter is independent — they MUST NOT import from one another.
The reconciler consumes the canonical output of both.
"""

from .pdf_adapter import PDFExtractionInput, load_pdf_facts
from .xbrl_adapter import XBRLExtractionInput, load_labels, load_xbrl_facts

__all__ = [
    "PDFExtractionInput",
    "XBRLExtractionInput",
    "load_labels",
    "load_pdf_facts",
    "load_xbrl_facts",
]
