"""Command-line interface: ``evaluate-report``.

Modes:

  * Single pair:  --pdf FILE --xbrl FILE --out DIR
  * Batch:        --pdf-dir DIR --xbrl-dir DIR --out DIR
  * Dry run:      add --dry-run to either mode to print without writing
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import traceback
from collections import defaultdict
from pathlib import Path
from typing import Any

from .adapters import load_pdf_facts, load_xbrl_facts
from .logger import append_run_log, utcnow_iso
from .reconciler import reconcile
from .reporter import build_report, write_diff_report, write_json_report
from .schema import EvaluationReport
from .scorer import score

DEFAULT_LOG_PATH = Path("logs/run_log.jsonl")

logger = logging.getLogger("annual_report_evaluation")


# --------------------------------------------------------------------------
# argparse
# --------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="evaluate-report",
        description=(
            "Evaluate an LLM-based PDF extraction (pdf-extraction package) against "
            "XBRL ground truth (xbrl-extraction package) for one filing."
        ),
    )
    # single-pair
    p.add_argument("--pdf", type=Path, help="Path to a single pdf-extraction *.facts.json")
    p.add_argument("--xbrl", type=Path, help="Path to a single xbrl-extraction *.facts.json")
    # batch
    p.add_argument(
        "--pdf-dir",
        type=Path,
        help="Directory of pdf-extraction JSONs (auto-pair by ticker+fiscal_year).",
    )
    p.add_argument(
        "--xbrl-dir",
        type=Path,
        help="Directory of xbrl-extraction JSONs (auto-pair by ticker+fiscal_year).",
    )
    # common
    p.add_argument(
        "--out",
        type=Path,
        default=Path("data/output"),
        help="Output directory for evaluation reports (default: data/output).",
    )
    p.add_argument(
        "--labs",
        type=Path,
        help="Optional explicit path to a labs.json (single-pair mode only).",
    )
    p.add_argument(
        "--log",
        type=Path,
        default=DEFAULT_LOG_PATH,
        help=f"Path to the append-only run log (default: {DEFAULT_LOG_PATH}).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be evaluated and exit without writing reports.",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (-v for INFO, -vv for DEBUG).",
    )
    return p


# --------------------------------------------------------------------------
# main entry point
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    single = bool(args.pdf) and bool(args.xbrl)
    batch = bool(args.pdf_dir) and bool(args.xbrl_dir)

    if single == batch:
        # both true or both false
        parser.error(
            "Specify EITHER --pdf+--xbrl (single) OR --pdf-dir+--xbrl-dir (batch), not both."
        )

    if single:
        ok = _run_single(args.pdf, args.xbrl, args.out, args.log, args.dry_run, args.labs)
        return 0 if ok else 1

    # batch
    n_ok, n_fail = _run_batch(args.pdf_dir, args.xbrl_dir, args.out, args.log, args.dry_run)
    if n_fail and not n_ok:
        return 1
    return 0


# --------------------------------------------------------------------------
# Single-pair runner
# --------------------------------------------------------------------------


def _run_single(
    pdf_path: Path,
    xbrl_path: Path,
    out_dir: Path,
    log_path: Path,
    dry_run: bool,
    labs_path: Path | None,
) -> bool:
    """Process one (pdf, xbrl) pair. Returns True on success."""
    started = time.perf_counter()
    pdf_input = None
    xbrl_input = None
    ticker = None
    fiscal_year = None
    period_end = None
    error: str | None = None

    try:
        pdf_input = load_pdf_facts(pdf_path)
        xbrl_input = load_xbrl_facts(xbrl_path, labs_path=labs_path)

        ticker = pdf_input.ticker or _guess_ticker_from_filename(pdf_path)
        fiscal_year = pdf_input.fiscal_year
        period_end = pdf_input.period_end

        # Sanity check: fiscal years should agree.
        if pdf_input.fiscal_year != xbrl_input.fiscal_year:
            logger.warning(
                "Fiscal year mismatch: pdf=%s xbrl=%s",
                pdf_input.fiscal_year,
                xbrl_input.fiscal_year,
            )

        print(f"Evaluating {ticker or '<unknown ticker>'} FY{fiscal_year}...")
        print()
        print(f"  XBRL facts in scope:  {len(xbrl_input.facts)}")
        print(f"  PDF facts in scope:   {len(pdf_input.facts)}")

        result = reconcile(pdf_input.facts, xbrl_input.facts, labels=xbrl_input.labels)
        scores = score(result)

        tier1 = sum(1 for p in result.matched if p.match_tier == 1)
        tier2 = sum(1 for p in result.matched if p.match_tier == 2)
        print(
            f"  Matched:              {len(result.matched):>3}"
            f"  (Tier 1: {tier1} · Tier 2: {tier2})"
        )
        print(f"  Missed:               {len(result.missed):>3}")
        print(f"  Spurious:             {len(result.spurious):>3}")
        print()
        print(f"  Coverage:   {scores.overall.coverage:.1%}")
        print(
            f"  Precision:  {scores.overall.precision:.1%}  "
            f"Recall:  {scores.overall.recall:.1%}  "
            f"F1:  {scores.overall.f1:.1%}"
        )
        print(
            f"  Exact:      {scores.overall.exact_match_rate:.1%}  "
            f"≤1%:  {scores.overall.within_1pct_rate:.1%}  "
            f"≤5%:  {scores.overall.within_5pct_rate:.1%}"
        )

        if dry_run:
            print()
            print("  [dry-run] no files written.")
            return True

        report = build_report(
            ticker=ticker,
            fiscal_year=fiscal_year,
            period_end=period_end,
            pdf_source=pdf_path.name,
            xbrl_source=xbrl_path.name,
            result=result,
            scores=scores,
        )
        json_out = write_json_report(report, out_dir, ticker)
        diff_out = write_diff_report(report, result, out_dir, ticker)

        print()
        print(f"  → wrote {json_out.name}")
        print(f"  → wrote {diff_out.name}")

        elapsed = time.perf_counter() - started
        _log_run(
            log_path=log_path,
            ticker=ticker,
            fiscal_year=fiscal_year,
            pdf_source=pdf_path.name,
            xbrl_source=xbrl_path.name,
            status="success",
            elapsed=elapsed,
            report=report,
            json_out=json_out.name,
            diff_out=diff_out.name,
        )
        return True

    except Exception as e:
        error = f"{type(e).__name__}: {e}"
        logger.error("Single-pair evaluation failed: %s", error)
        if logger.isEnabledFor(logging.DEBUG):
            traceback.print_exc()
        elapsed = time.perf_counter() - started
        _log_run(
            log_path=log_path,
            ticker=ticker,
            fiscal_year=fiscal_year,
            pdf_source=pdf_path.name,
            xbrl_source=xbrl_path.name,
            status="failure",
            elapsed=elapsed,
            report=None,
            json_out=None,
            diff_out=None,
            error=error,
        )
        return False


# --------------------------------------------------------------------------
# Batch runner
# --------------------------------------------------------------------------


def _run_batch(
    pdf_dir: Path,
    xbrl_dir: Path,
    out_dir: Path,
    log_path: Path,
    dry_run: bool,
) -> tuple[int, int]:
    """Process every matched pair in pdf_dir x xbrl_dir. Returns (n_ok, n_fail)."""
    if not pdf_dir.exists():
        logger.error("PDF directory does not exist: %s", pdf_dir)
        return (0, 0)
    if not xbrl_dir.exists():
        logger.error("XBRL directory does not exist: %s", xbrl_dir)
        return (0, 0)

    pdf_files = sorted(pdf_dir.glob("*.facts.json"))
    xbrl_files = sorted(xbrl_dir.glob("*.facts.json"))

    pairs, unmatched = _auto_pair_files(pdf_files, xbrl_files)

    if unmatched:
        for f in unmatched:
            logger.warning("Unpaired file (no counterpart found): %s", f)

    if not pairs:
        logger.error("No pairable files found in %s x %s", pdf_dir, xbrl_dir)
        return (0, 0)

    print(f"Batch evaluation: {len(pairs)} pair(s) to process.")
    n_ok = n_fail = 0
    for pdf_path, xbrl_path in pairs:
        print()
        ok = _run_single(pdf_path, xbrl_path, out_dir, log_path, dry_run, labs_path=None)
        if ok:
            n_ok += 1
        else:
            n_fail += 1

    print()
    print(f"Batch complete: {n_ok} succeeded, {n_fail} failed.")
    return (n_ok, n_fail)


def _auto_pair_files(
    pdf_files: list[Path], xbrl_files: list[Path]
) -> tuple[list[tuple[Path, Path]], list[Path]]:
    """Pair PDF and XBRL files by (ticker, fiscal_year), reading metadata.

    Returns (pairs, unmatched_files).
    """
    pdf_index: dict[tuple[Any, int], Path] = {}
    pdf_unmatched_keys: dict[Path, tuple[Any, int]] = {}
    for p in pdf_files:
        meta = _read_meta(p, kind="pdf")
        if meta is None:
            continue
        ticker, fy = meta
        key = (ticker, fy)
        pdf_index[key] = p
        pdf_unmatched_keys[p] = key

    xbrl_index: dict[tuple[Any, int], Path] = {}
    xbrl_unmatched_keys: dict[Path, tuple[Any, int]] = {}
    for x in xbrl_files:
        meta = _read_meta(x, kind="xbrl")
        if meta is None:
            continue
        ticker, fy = meta
        key = (ticker, fy)
        xbrl_index[key] = x
        xbrl_unmatched_keys[x] = key

    pairs: list[tuple[Path, Path]] = []
    matched_keys = set(pdf_index.keys()) & set(xbrl_index.keys())
    for key in sorted(matched_keys, key=lambda k: (str(k[0]) or "", k[1])):
        pairs.append((pdf_index[key], xbrl_index[key]))

    # If ticker is missing on the XBRL side, fall back to fiscal_year-only pairing
    # for any leftover PDFs whose key wasn't matched. This is best-effort.
    leftover_pdf = [p for p, k in pdf_unmatched_keys.items() if k not in matched_keys]
    leftover_xbrl = [x for x, k in xbrl_unmatched_keys.items() if k not in matched_keys]

    pdf_by_fy: dict[int, list[Path]] = defaultdict(list)
    xbrl_by_fy: dict[int, list[Path]] = defaultdict(list)
    for p in leftover_pdf:
        pdf_by_fy[pdf_unmatched_keys[p][1]].append(p)
    for x in leftover_xbrl:
        xbrl_by_fy[xbrl_unmatched_keys[x][1]].append(x)

    fy_matched_pdf: set[Path] = set()
    fy_matched_xbrl: set[Path] = set()
    for fy, pdfs in pdf_by_fy.items():
        xs = xbrl_by_fy.get(fy, [])
        if len(pdfs) == 1 and len(xs) == 1:
            pairs.append((pdfs[0], xs[0]))
            fy_matched_pdf.add(pdfs[0])
            fy_matched_xbrl.add(xs[0])

    unmatched = [p for p in leftover_pdf if p not in fy_matched_pdf]
    unmatched += [x for x in leftover_xbrl if x not in fy_matched_xbrl]

    return pairs, unmatched


def _read_meta(path: Path, *, kind: str) -> tuple[str | None, int] | None:
    """Read just enough JSON to get (ticker, fiscal_year). None on failure."""
    try:
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as e:
        logger.warning("Could not read %s: %s", path, e)
        return None
    filing = payload.get("filing") or {}
    entity = payload.get("entity") or {}
    fy = filing.get("fiscal_year")
    if fy is None:
        logger.warning("No filing.fiscal_year in %s — skipping.", path)
        return None
    ticker = entity.get("ticker") or entity.get("cik")
    if ticker is None:
        ticker = _guess_ticker_from_filename(path)
    return (ticker, int(fy))


def _guess_ticker_from_filename(path: Path) -> str | None:
    """Best-effort ticker guess from a filename like AAPL_FY2024.facts.json or aapl.facts.json."""
    stem = path.name
    for suffix in (".facts.json", ".json"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    # AAPL_FY2024 → AAPL
    if "_FY" in stem:
        return stem.split("_FY", 1)[0].upper() or None
    # Plain "aapl" → AAPL
    if stem.isalnum():
        return stem.upper()
    return None


# --------------------------------------------------------------------------
# logging + run-log helpers
# --------------------------------------------------------------------------


def _configure_logging(verbose: int) -> None:
    level = logging.WARNING
    if verbose == 1:
        level = logging.INFO
    elif verbose >= 2:
        level = logging.DEBUG
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _log_run(
    *,
    log_path: Path,
    ticker: str | None,
    fiscal_year: int | None,
    pdf_source: str,
    xbrl_source: str,
    status: str,
    elapsed: float,
    report: EvaluationReport | None,
    json_out: str | None,
    diff_out: str | None,
    error: str | None = None,
) -> None:
    """Append one run record to the log."""
    record: dict[str, Any] = {
        "ts": utcnow_iso(),
        "ticker": ticker,
        "fiscal_year": fiscal_year,
        "pdf_source": pdf_source,
        "xbrl_source": xbrl_source,
        "status": status,
        "elapsed_seconds": round(elapsed, 3),
        "xbrl_facts_scope": None,
        "pdf_facts_scope": None,
        "matched": None,
        "missed": None,
        "spurious": None,
        "tier1_matches": None,
        "tier2_matches": None,
        "overall_f1": None,
        "overall_coverage": None,
        "exact_match_rate": None,
        "within_1pct_rate": None,
        "within_5pct_rate": None,
        "output_json": json_out,
        "output_diff": diff_out,
        "error": error,
    }
    if report is not None:
        s = report.scores.overall
        summary = report.summary
        record.update(
            {
                "xbrl_facts_scope": summary.xbrl_facts_in_scope,
                "pdf_facts_scope": summary.pdf_facts_in_scope,
                "matched": summary.matched,
                "missed": summary.missed,
                "spurious": summary.spurious,
                "tier1_matches": summary.tier1_matches,
                "tier2_matches": summary.tier2_matches,
                "overall_f1": round(s.f1, 4),
                "overall_coverage": round(s.coverage, 4),
                "exact_match_rate": round(s.exact_match_rate, 4),
                "within_1pct_rate": round(s.within_1pct_rate, 4),
                "within_5pct_rate": round(s.within_5pct_rate, 4),
            }
        )
    append_run_log(log_path, record)


if __name__ == "__main__":
    raise SystemExit(main())
