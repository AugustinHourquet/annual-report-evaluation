"""Pure utility helpers used by the adapters and reconciler.

No I/O, no side effects. Keep them tiny and unit-testable.
"""

from __future__ import annotations

import re
from typing import Final

from .schema import FinancialFact

# --------------------------------------------------------------------------
# Value normalisation
# --------------------------------------------------------------------------

PDF_SCALE_MAP: Final[dict[str, int]] = {
    "millions": 1_000_000,
    "thousands": 1_000,
    "billions": 1_000_000_000,
    "actual": 1,
}


def normalise_pdf_value(value: float, scale: str) -> float:
    """Apply a pdf-extraction scale string to a raw value.

    Raises:
        ValueError: if `scale` is not one of the four documented values.
    """
    if scale not in PDF_SCALE_MAP:
        raise ValueError(
            f"Unknown PDF scale {scale!r}. " f"Expected one of {sorted(PDF_SCALE_MAP)}."
        )
    return float(value) * PDF_SCALE_MAP[scale]


def normalise_xbrl_value(value: float, scale: str | int) -> float:
    """Apply an xbrl-extraction scale (integer string like "6") to a raw value.

    A scale of "6" means the as-filed value is in millions; multiply by 10**6.
    """
    try:
        exponent = int(scale)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Malformed XBRL scale {scale!r}: must be an integer string.") from exc
    return float(value) * (10**exponent)


# --------------------------------------------------------------------------
# Period overlap
# --------------------------------------------------------------------------


def period_overlap(a: FinancialFact, b: FinancialFact) -> bool:
    """Return True iff facts a and b share the same fiscal period.

    Rules:
        - period_type must match. A duration never matches an instant.
        - For duration: same fiscal_year.
        - For instant:  same period_end date.
    """
    if a.period_type != b.period_type:
        return False
    if a.period_type == "duration":
        return a.fiscal_year == b.fiscal_year
    # instant
    return a.period_end == b.period_end


# --------------------------------------------------------------------------
# Concept → statement mapping
# --------------------------------------------------------------------------
#
# The XBRL JSON has no statement label — we have to derive one from the
# concept name for per-statement reporting. This is best-effort.
#
# The map covers the common us-gaap concepts found in the four v1 statements.
# Anything not in the map and not matched by a regex pattern falls through
# to "Unknown" — it will still participate in overall scoring, but won't
# contribute to a per-statement breakdown.

_CONCEPT_TO_STATEMENT: Final[dict[str, str]] = {
    # ---------------- Income Statement ----------------
    "us-gaap:Revenues": "IncomeStatement",
    "us-gaap:Revenue": "IncomeStatement",
    "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax": "IncomeStatement",
    "us-gaap:RevenueFromContractWithCustomerIncludingAssessedTax": "IncomeStatement",
    "us-gaap:SalesRevenueNet": "IncomeStatement",
    "us-gaap:SalesRevenueGoodsNet": "IncomeStatement",
    "us-gaap:SalesRevenueServicesNet": "IncomeStatement",
    "us-gaap:CostOfRevenue": "IncomeStatement",
    "us-gaap:CostOfGoodsSold": "IncomeStatement",
    "us-gaap:CostOfGoodsAndServicesSold": "IncomeStatement",
    "us-gaap:GrossProfit": "IncomeStatement",
    "us-gaap:OperatingExpenses": "IncomeStatement",
    "us-gaap:ResearchAndDevelopmentExpense": "IncomeStatement",
    "us-gaap:SellingGeneralAndAdministrativeExpense": "IncomeStatement",
    "us-gaap:GeneralAndAdministrativeExpense": "IncomeStatement",
    "us-gaap:SellingAndMarketingExpense": "IncomeStatement",
    "us-gaap:OperatingIncomeLoss": "IncomeStatement",
    "us-gaap:NonoperatingIncomeExpense": "IncomeStatement",
    "us-gaap:InterestExpense": "IncomeStatement",
    "us-gaap:InterestIncomeOperating": "IncomeStatement",
    "us-gaap:OtherNonoperatingIncomeExpense": "IncomeStatement",
    "us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": "IncomeStatement",
    "us-gaap:IncomeTaxExpenseBenefit": "IncomeStatement",
    "us-gaap:NetIncomeLoss": "IncomeStatement",
    "us-gaap:EarningsPerShareBasic": "IncomeStatement",
    "us-gaap:EarningsPerShareDiluted": "IncomeStatement",
    "us-gaap:WeightedAverageNumberOfSharesOutstandingBasic": "IncomeStatement",
    "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding": "IncomeStatement",
    # ---------------- Balance Sheet ----------------
    "us-gaap:Assets": "BalanceSheet",
    "us-gaap:AssetsCurrent": "BalanceSheet",
    "us-gaap:AssetsNoncurrent": "BalanceSheet",
    "us-gaap:Cash": "BalanceSheet",
    "us-gaap:CashAndCashEquivalentsAtCarryingValue": "BalanceSheet",
    "us-gaap:ShortTermInvestments": "BalanceSheet",
    "us-gaap:MarketableSecuritiesCurrent": "BalanceSheet",
    "us-gaap:MarketableSecuritiesNoncurrent": "BalanceSheet",
    "us-gaap:AccountsReceivableNetCurrent": "BalanceSheet",
    "us-gaap:InventoryNet": "BalanceSheet",
    "us-gaap:Inventory": "BalanceSheet",
    "us-gaap:NontradeReceivablesCurrent": "BalanceSheet",
    "us-gaap:OtherAssetsCurrent": "BalanceSheet",
    "us-gaap:OtherAssetsNoncurrent": "BalanceSheet",
    "us-gaap:Goodwill": "BalanceSheet",
    "us-gaap:IntangibleAssetsNetExcludingGoodwill": "BalanceSheet",
    "us-gaap:OperatingLeaseRightOfUseAsset": "BalanceSheet",
    "us-gaap:Liabilities": "BalanceSheet",
    "us-gaap:LiabilitiesCurrent": "BalanceSheet",
    "us-gaap:LiabilitiesNoncurrent": "BalanceSheet",
    "us-gaap:AccountsPayableCurrent": "BalanceSheet",
    "us-gaap:OtherLiabilitiesCurrent": "BalanceSheet",
    "us-gaap:OtherLiabilitiesNoncurrent": "BalanceSheet",
    "us-gaap:CommercialPaper": "BalanceSheet",
    "us-gaap:LongTermDebt": "BalanceSheet",
    "us-gaap:LongTermDebtCurrent": "BalanceSheet",
    "us-gaap:LongTermDebtNoncurrent": "BalanceSheet",
    "us-gaap:OperatingLeaseLiabilityCurrent": "BalanceSheet",
    "us-gaap:OperatingLeaseLiabilityNoncurrent": "BalanceSheet",
    "us-gaap:ContractWithCustomerLiabilityCurrent": "BalanceSheet",
    "us-gaap:CommitmentsAndContingencies": "BalanceSheet",
    "us-gaap:StockholdersEquity": "BalanceSheet",
    "us-gaap:CommonStockValue": "BalanceSheet",
    "us-gaap:CommonStocksIncludingAdditionalPaidInCapital": "BalanceSheet",
    "us-gaap:RetainedEarningsAccumulatedDeficit": "BalanceSheet",
    "us-gaap:AccumulatedOtherComprehensiveIncomeLossNetOfTax": "BalanceSheet",
    "us-gaap:LiabilitiesAndStockholdersEquity": "BalanceSheet",
    # ---------------- Cash Flow ----------------
    "us-gaap:NetCashProvidedByUsedInOperatingActivities": "CashFlow",
    "us-gaap:NetCashProvidedByUsedInInvestingActivities": "CashFlow",
    "us-gaap:NetCashProvidedByUsedInFinancingActivities": "CashFlow",
    "us-gaap:DepreciationDepletionAndAmortization": "CashFlow",
    "us-gaap:ShareBasedCompensation": "CashFlow",
    "us-gaap:OtherNoncashIncomeExpense": "CashFlow",
    "us-gaap:IncreaseDecreaseInAccountsReceivable": "CashFlow",
    "us-gaap:IncreaseDecreaseInInventories": "CashFlow",
    "us-gaap:IncreaseDecreaseInOtherOperatingCapitalNet": "CashFlow",
    "us-gaap:IncreaseDecreaseInAccountsPayable": "CashFlow",
    "us-gaap:IncreaseDecreaseInContractWithCustomerLiability": "CashFlow",
    "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment": "CashFlow",
    "us-gaap:PaymentsToAcquireBusinessesNetOfCashAcquired": "CashFlow",
    "us-gaap:PaymentsToAcquireMarketableSecurities": "CashFlow",
    "us-gaap:ProceedsFromMaturitiesPrepaymentsAndCallsOfAvailableForSaleSecurities": "CashFlow",
    "us-gaap:ProceedsFromSaleOfAvailableForSaleSecurities": "CashFlow",
    "us-gaap:ProceedsFromIssuanceOfLongTermDebt": "CashFlow",
    "us-gaap:RepaymentsOfLongTermDebt": "CashFlow",
    "us-gaap:ProceedsFromRepaymentsOfCommercialPaper": "CashFlow",
    "us-gaap:PaymentsOfDividends": "CashFlow",
    "us-gaap:PaymentsForRepurchaseOfCommonStock": "CashFlow",
    "us-gaap:ProceedsFromIssuanceOfCommonStock": "CashFlow",
    "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect": "CashFlow",
    # ---------------- PPE Note ----------------
    "us-gaap:PropertyPlantAndEquipmentGross": "Note_PPE",
    "us-gaap:PropertyPlantAndEquipmentNet": "Note_PPE",
    "us-gaap:AccumulatedDepreciationDepletionAndAmortizationPropertyPlantAndEquipment": "Note_PPE",
    "us-gaap:LandAndLandImprovements": "Note_PPE",
    "us-gaap:BuildingsAndImprovementsGross": "Note_PPE",
    "us-gaap:MachineryAndEquipmentGross": "Note_PPE",
    "us-gaap:LeaseholdImprovementsGross": "Note_PPE",
    "us-gaap:ConstructionInProgressGross": "Note_PPE",
    "us-gaap:Depreciation": "Note_PPE",
}

# Patterns for last-resort classification when the concept isn't in the map.
# Ordered: first match wins.
_STATEMENT_PATTERNS: Final[list[tuple[re.Pattern[str], str]]] = [
    (re.compile(r"(?i)CashFlow|CashProvidedByUsed", re.IGNORECASE), "CashFlow"),
    (re.compile(r"(?i)PropertyPlantAndEquipment|AccumulatedDepreciation"), "Note_PPE"),
    (re.compile(r"(?i)Revenue|Expense|Income|EarningsPerShare|GrossProfit"), "IncomeStatement"),
    (re.compile(r"(?i)Asset|Liabilit|StockholdersEquity|RetainedEarnings"), "BalanceSheet"),
]


def concept_to_statement(concept: str) -> str:
    """Best-effort: classify an XBRL concept into one of the four v1 statements.

    Returns "Unknown" when no rule applies. Unknown facts are still in scope
    (no dimensions = in scope), but they are excluded from per-statement
    breakdowns to avoid noise.
    """
    if concept in _CONCEPT_TO_STATEMENT:
        return _CONCEPT_TO_STATEMENT[concept]
    for pattern, statement in _STATEMENT_PATTERNS:
        if pattern.search(concept):
            return statement
    return "Unknown"


# --------------------------------------------------------------------------
# Miscellaneous helpers
# --------------------------------------------------------------------------


def safe_div(numerator: float, denominator: float) -> float:
    """Return numerator/denominator, or 0.0 when denominator is zero."""
    if denominator == 0:
        return 0.0
    return numerator / denominator
