# ==============================================================================
# VERNIMMEN FINANCIAL ENGINE
# QuickBooks ingestion + four-stage financial analysis (Vernimmen, "Corporate
# Finance: Theory and Practice"): Wealth Creation, Investment Policy, Financing
# Policy, Returns. Adapted for Streamlit from a Colab-oriented prototype:
# no filesystem/Colab dependencies, audit trail is per-run (not a module
# global), and every entry point works directly off uploaded file objects.
# ==============================================================================
from __future__ import annotations

import re
import datetime as dt
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

EPS = 1e-9


class CFG:
    """Analytical parameters. Tune the engine here, never inside the logic."""

    TREND_THRESHOLD = 0.10   # |MoM| above this is flagged as a notable move
    TAX_RATE = 0.00          # LLC / pass-through default -> NOPAT = EBIT
    PERIODS_PER_YEAR = 12
    DAYS_IN_PERIOD = 30.4

    ND_EBITDA_CEILING = 3.0
    CURRENT_RATIO_MIN = 1.0
    QUICK_RATIO_MIN = 1.0
    MIN_EQUITY_RATIO = 0.10  # ROE suppressed below this share of capital employed


class AuditLog:
    """Every assumption, fallback and data-quality issue, in one place.

    Kept as an instance (not a module global) so a fresh run — a new upload in
    the same Streamlit session — never inherits findings from the previous one.
    """

    def __init__(self):
        self.entries: list[dict] = []

    def log(self, level: str, area: str, message: str):
        self.entries.append({"Severity": level, "Area": area, "Finding": message})

    def errors(self):
        return [a for a in self.entries if a["Severity"] == "ERROR"]

    def warnings(self):
        return [a for a in self.entries if a["Severity"] == "WARNING"]


# ------------------------------------------------------------------------------
# INGESTION — resilient to QuickBooks' messy header structures
# ------------------------------------------------------------------------------
PERIOD_RE = re.compile(
    r"^\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{4}\s*$"
    r"|^\s*q[1-4]\s+\d{4}\s*$"
    r"|^\s*\d{1,2}/\d{1,2}/\d{2,4}\s*$",
    re.IGNORECASE,
)
FOOTER_RE = re.compile(r"GMT[+\-]|accrual basis|cash basis", re.IGNORECASE)
NOISE_COL_RE = re.compile(r"^\s*(total|%\s*of|unnamed|average|change)", re.IGNORECASE)


class ParseError(ValueError):
    """A CSV could not be read as a QuickBooks export."""


@dataclass
class Statement:
    """A cleaned QuickBooks statement: tidy rows, typed numbers, ordered periods."""

    kind: str  # 'PL' | 'BS' | 'CF'
    df: pd.DataFrame
    periods: list
    entity: str = ""
    title: str = ""
    resolved: dict = field(default_factory=dict)  # concept -> matched QB label


def _to_number(x) -> float:
    """QuickBooks writes '$1,234.56', '(1,234.56)', '-', '' and stray spaces."""
    s = str(x).strip()
    if s in ("", "-", "nan", "None", "—"):
        return 0.0
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace("$", "").replace(",", "").replace(" ", "").strip()
    try:
        v = float(s)
    except ValueError:
        return 0.0
    return -v if neg else v


def _norm(label) -> str:
    s = re.sub(r"\s+", " ", str(label)).strip().rstrip(":").lower()
    return s


def _detect_header_row(raw: pd.DataFrame, scan: int = 15) -> int:
    """The header is the first row carrying >=2 recognisable period labels."""
    best_idx, best_hits = None, 0
    for i in range(min(scan, len(raw))):
        hits = sum(bool(PERIOD_RE.match(str(c))) for c in raw.iloc[i])
        if hits > best_hits:
            best_idx, best_hits = i, hits
    if best_idx is None or best_hits < 2:
        raise ParseError(
            "No monthly/quarterly column header found — this doesn't look like a "
            "QuickBooks export (expected columns like 'Jan 2026', 'Feb 2026', ...)."
        )
    return best_idx


def read_qb(source, name: str = "") -> Statement:
    """Parse one QuickBooks CSV into a Statement (structure-driven, not position-driven)."""
    if hasattr(source, "seek"):
        source.seek(0)
    raw = pd.read_csv(source, header=None, dtype=str, keep_default_na=False,
                       skip_blank_lines=False)

    hdr = _detect_header_row(raw)
    entity = str(raw.iloc[0, 0]).strip() if hdr > 0 else ""
    title = str(raw.iloc[1, 0]).strip() if hdr > 1 else ""

    df = raw.iloc[hdr + 1:].copy()
    df.columns = [str(c).strip() for c in raw.iloc[hdr]]
    df = df.rename(columns={df.columns[0]: "Account"})

    df["Account"] = df["Account"].astype(str).str.strip()
    df = df[df["Account"] != ""]
    df = df[~df["Account"].str.contains(FOOTER_RE)]

    periods = [c for c in df.columns
               if PERIOD_RE.match(str(c)) and not NOISE_COL_RE.match(str(c))]
    if not periods:
        raise ParseError(f"{name}: no monthly/quarterly columns detected.")

    for c in periods:
        df[c] = df[c].map(_to_number)

    def _key(label):
        for fmt in ("%b %Y", "%B %Y", "%m/%d/%Y", "%m/%d/%y"):
            try:
                return dt.datetime.strptime(str(label).strip(), fmt)
            except ValueError:
                continue
        m = re.match(r"\s*q([1-4])\s+(\d{4})", str(label), re.IGNORECASE)
        if m:
            return dt.datetime(int(m.group(2)), int(m.group(1)) * 3, 1)
        return dt.datetime.max
    periods = sorted(periods, key=_key)

    df = df[["Account"] + periods].reset_index(drop=True)

    blob = " | ".join(df["Account"].map(_norm)) + " " + _norm(title)
    if "net cash provided by operating activities" in blob or "operating activities" in blob:
        kind = "CF"
    elif "total for liabilities and equity" in blob or "total liabilities and equity" in blob:
        kind = "BS"
    elif "gross profit" in blob or "net operating income" in blob:
        kind = "PL"
    else:
        kind = "UNKNOWN"

    return Statement(kind=kind, df=df, periods=periods, entity=entity, title=title)


def _dedupe(stmt: Statement, audit: AuditLog):
    """Duplicate subtotal rows are a known QuickBooks export artefact."""
    dup_mask = stmt.df.duplicated(subset=["Account"], keep=False)
    for lbl in stmt.df.loc[dup_mask, "Account"].unique():
        blk = stmt.df[stmt.df["Account"] == lbl][stmt.periods]
        if not blk.duplicated(keep=False).all():
            audit.log("WARNING", "Ingestion",
                       f"{stmt.kind}: '{lbl}' appears {len(blk)}x with different values "
                       "— the last occurrence was used.")


# ------------------------------------------------------------------------------
# LINE-ITEM RESOLVER — statement-scoped, exact-first, auditable
# ------------------------------------------------------------------------------
def resolve(stmt: Statement, audit: AuditLog, concept: str, exact: list,
            contains: list | None = None, exclude: list | None = None,
            required: bool = False) -> pd.Series:
    """Extract one concept as a time series, and record HOW it was found."""
    d, P = stmt.df, stmt.periods
    keys = d["Account"].map(_norm)

    for lbl in exact:
        hit = d[keys == _norm(lbl)]
        if not hit.empty:
            stmt.resolved[concept] = f"{lbl} (exact)"
            return hit.iloc[-1][P].astype(float)

    for pat in (contains or []):
        m = keys.str.contains(_norm(pat), regex=False, na=False)
        if exclude:
            for ex in exclude:
                m &= ~keys.str.contains(_norm(ex), regex=False, na=False)
        hit = d[m]
        if not hit.empty:
            matched = hit.iloc[-1]["Account"]
            stmt.resolved[concept] = f"{matched} (fuzzy)"
            audit.log("WARNING", "Mapping",
                       f"{concept}: no exact label match — used '{matched}' instead.")
            return hit.iloc[-1][P].astype(float)

    stmt.resolved[concept] = "NOT FOUND -> 0.0"
    audit.log("ERROR" if required else "INFO", "Mapping",
               f"{concept}: not found in {stmt.kind}. Treated as zero"
               + (" — dependent metrics are unreliable." if required else "."))
    return pd.Series(0.0, index=P, dtype=float)


def sum_rows(stmt: Statement, concept: str, labels: list) -> pd.Series:
    """Sum several distinct detail rows (e.g. two separate interest accounts)."""
    total = pd.Series(0.0, index=stmt.periods, dtype=float)
    found = []
    keys = stmt.df["Account"].map(_norm)
    for lbl in labels:
        hit = stmt.df[keys == _norm(lbl)]
        if not hit.empty:
            total += hit.iloc[-1][stmt.periods].astype(float)
            found.append(lbl)
    stmt.resolved[concept] = " + ".join(found) if found else "NOT FOUND -> 0.0"
    return total


# ------------------------------------------------------------------------------
# MATH GUARDS
# ------------------------------------------------------------------------------
def sdiv(num, den, floor: float = EPS) -> pd.Series:
    """Division that returns NaN (not 0, not inf) where the denominator is unusable."""
    num = pd.Series(num, dtype=float)
    den = pd.Series(den, dtype=float)
    out = num / den.where(den.abs() > floor)
    return out.replace([np.inf, -np.inf], np.nan)


def mean_balance(stock: pd.Series) -> pd.Series:
    return stock.expanding().mean()


def ytd_annualised(flow: pd.Series) -> pd.Series:
    """Cumulative flow to date, scaled to a full year — avoids one strong/weak
    month distorting an annualised ratio (e.g. Net Debt/EBITDA)."""
    n = pd.Series(np.arange(1, len(flow) + 1), index=flow.index)
    return flow.expanding().sum() * CFG.PERIODS_PER_YEAR / n


def pct_change(s: pd.Series) -> pd.Series:
    return sdiv(s.diff(), s.shift(1).abs())


# ------------------------------------------------------------------------------
# THE ENGINE — Vernimmen four-stage build
# ------------------------------------------------------------------------------
def build_engine(pl: Statement, bs: Statement, cf: Statement, audit: AuditLog) -> pd.DataFrame:
    for stmt in (pl, bs, cf):
        _dedupe(stmt, audit)

    P = [p for p in pl.periods if p in set(bs.periods) & set(cf.periods)]
    if not P:
        raise ParseError(
            "The three statements don't share any common months. Make sure the "
            "P&L, Balance Sheet and Cash Flow exports cover the same date range."
        )
    for stmt in (pl, bs, cf):
        dropped = [p for p in stmt.periods if p not in P]
        if dropped:
            audit.log("WARNING", "Alignment",
                       f"{stmt.kind}: periods {dropped} excluded (not present in all three statements).")
        stmt.periods = P

    CFG.PERIODS_PER_YEAR = 12
    M = pd.DataFrame(index=P)

    # ========== STAGE 1 - WEALTH CREATION ====================================
    sales = resolve(pl, audit, "Sales", ["Total for Income", "Total Income"],
                     contains=["income"], exclude=["net", "other", "cost"], required=True)
    cogs = resolve(pl, audit, "COGS", ["Total for Cost of Goods Sold", "Total Cost of Goods Sold"],
                    contains=["cost of goods"], required=True)
    gross = resolve(pl, audit, "Gross Profit", ["Gross Profit"])
    opex_reported = resolve(pl, audit, "Operating Expenses (reported)",
                             ["Total for Expenses", "Total Expenses", "Total Expense"],
                             contains=["total for expenses", "total expense"], required=True)
    net_income = resolve(pl, audit, "Net Income", ["Net Income"], required=True)

    # QuickBooks books interest inside operating expenses. Vernimmen treats
    # interest as a financing cost — leaving it in opex would contaminate EBIT,
    # EBITDA and the whole leverage analysis, so it's reclassified out here.
    interest = sum_rows(pl, "Interest Expense (reclassified)",
                         ["Interest Expense", "Credit Card Interest Expense",
                          "Total for Interest Expense", "Loan Interest Expense"])
    if interest.abs().sum() > 0:
        audit.log("INFO", "Reclassification",
                   f"Interest of {interest.sum():,.0f} moved out of operating expenses into "
                   "financing, per the Vernimmen framework. EBIT is restated accordingly.")

    dep = sum_rows(pl, "Depreciation & Amortisation",
                    ["Depreciation", "Depreciation Expense", "Amortization",
                     "Amortisation", "Total for Depreciation"])

    opex_core = opex_reported - interest - dep
    ebit = sales - cogs - opex_core - dep
    ebitda = ebit + dep

    if dep.abs().sum() < EPS:
        audit.log("ERROR", "Wealth Creation",
                   "No depreciation is booked anywhere in the P&L. EBITDA will equal EBIT, "
                   "capital employed is carried at gross cost, and ROCE will be overstated. "
                   "Book depreciation before sharing these returns outside the company.")

    M["Sales"] = sales
    M["COGS"] = cogs
    M["Gross Profit"] = gross.where(gross.abs() > EPS, sales - cogs)
    M["Operating Expenses (core)"] = opex_core
    M["Interest Expense"] = interest
    M["D&A"] = dep
    M["EBITDA"] = ebitda
    M["EBIT"] = ebit
    M["Net Income"] = net_income

    M["Gross Margin %"] = sdiv(M["Gross Profit"], sales) * 100
    M["EBITDA Margin %"] = sdiv(ebitda, sales) * 100
    M["EBIT Margin %"] = sdiv(ebit, sales) * 100
    M["Net Margin %"] = sdiv(net_income, sales) * 100

    M["Sales Growth %"] = pct_change(sales) * 100
    M["COGS Growth %"] = pct_change(cogs) * 100
    M["Opex Growth %"] = pct_change(opex_core) * 100

    total_cost = cogs + opex_core
    base_s = sales.iloc[0] if abs(sales.iloc[0]) > EPS else np.nan
    base_c = total_cost.iloc[0] if abs(total_cost.iloc[0]) > EPS else np.nan
    M["Sales Index (100)"] = sales / base_s * 100
    M["Cost Base Index (100)"] = total_cost / base_c * 100
    M["Scissors Gap (pts)"] = M["Sales Index (100)"] - M["Cost Base Index (100)"]

    # ========== STAGE 2 - INVESTMENT POLICY ==================================
    tot_assets = resolve(bs, audit, "Total Assets", ["Total for Assets", "Total Assets"], required=True)
    curr_assets = resolve(bs, audit, "Current Assets",
                           ["Total for Current Assets", "Total Current Assets"], required=True)
    curr_liab = resolve(bs, audit, "Current Liabilities",
                         ["Total for Current Liabilities", "Total Current Liabilities"], required=True)
    fixed_assets = resolve(bs, audit, "Fixed Assets (net)",
                            ["Total for Fixed Assets", "Total Fixed Assets"],
                            contains=["fixed assets"])
    inventory = resolve(bs, audit, "Inventory", ["Inventory Asset", "Total for Inventory", "Inventory"])
    receivables = resolve(bs, audit, "Accounts Receivable",
                           ["Total for Accounts Receivable", "Accounts Receivable (A/R)"],
                           contains=["accounts receivable"])
    payables = resolve(bs, audit, "Accounts Payable",
                        ["Total for Accounts Payable", "Accounts Payable (A/P)"],
                        contains=["accounts payable"])
    cash = resolve(bs, audit, "Cash", ["Total for Bank Accounts", "Total Bank Accounts"],
                    contains=["bank accounts"], required=True)
    equity = resolve(bs, audit, "Equity", ["Total for Equity", "Total Equity"], required=True)
    lt_liab = resolve(bs, audit, "Long-term Liabilities",
                       ["Total for Long-term Liabilities", "Total Long-term Liabilities"],
                       contains=["long-term liabilities"])
    credit_cards = resolve(bs, audit, "Credit Cards (short-term debt)",
                            ["Total for Credit Cards", "Total Credit Cards"],
                            contains=["credit cards"])

    # Operating working capital (Vernimmen) = AR + Inventory - AP. Not the same
    # as accounting working capital (CA - CL), which can include non-operating
    # balances such as shareholder loans parked in current assets.
    owc = receivables + inventory - payables
    wc_accounting = curr_assets - curr_liab

    M["Working Capital (CA-CL)"] = wc_accounting
    M["Operating Working Capital"] = owc
    M["Fixed Assets"] = fixed_assets
    M["Total Assets"] = tot_assets
    M["Cash"] = cash
    M["Equity"] = equity

    cap_emp = fixed_assets + owc
    M["Capital Employed"] = cap_emp

    M["Current Ratio"] = sdiv(curr_assets, curr_liab)
    M["Quick Ratio"] = sdiv(curr_assets - inventory, curr_liab)

    M["WC Turnover (x)"] = sdiv(ytd_annualised(sales), mean_balance(owc))
    M["WC in Days of Sales"] = sdiv(owc, sales) * CFG.DAYS_IN_PERIOD
    M["DSO (days)"] = sdiv(receivables, sales) * CFG.DAYS_IN_PERIOD
    M["DIO (days)"] = sdiv(inventory, cogs) * CFG.DAYS_IN_PERIOD
    M["DPO (days)"] = sdiv(payables, cogs) * CFG.DAYS_IN_PERIOD
    M["Cash Conversion Cycle (days)"] = M["DSO (days)"] + M["DIO (days)"] - M["DPO (days)"]

    if receivables.nunique() == 1 and receivables.abs().sum() > 0:
        audit.log("WARNING", "Investment Policy",
                   "Accounts Receivable never changes month to month, so DSO and the cash "
                   "conversion cycle are not meaningful — treat as a bookkeeping gap.")
    if inventory.nunique() == 1 and inventory.abs().sum() > 0:
        audit.log("WARNING", "Investment Policy",
                   "Inventory never changes month to month, so days-inventory-outstanding "
                   "is not meaningful.")
    if payables.abs().sum() < EPS:
        audit.log("WARNING", "Investment Policy",
                   "No Accounts Payable balance exists — supplier credit may be running "
                   "through credit cards instead, converting free trade credit into "
                   "interest-bearing debt.")

    inv_cf = resolve(cf, audit, "Investing Cash Flow",
                      ["Net cash provided by investing activities",
                       "Net cash used in investing activities"],
                      contains=["investing activities"])
    capex = -inv_cf.clip(upper=0)
    if capex.abs().sum() < EPS:
        capex = fixed_assets.diff().clip(lower=0).fillna(0)
        audit.log("WARNING", "Investment Policy", "Capex estimated from fixed-asset movement (no investing-activities line found).")
    M["Capex"] = capex
    M["Capex / Sales %"] = sdiv(capex, sales) * 100
    M["Capex / D&A (x)"] = sdiv(capex, dep)

    # ========== STAGE 3 - FINANCING POLICY ===================================
    op_cf = resolve(cf, audit, "Operating Cash Flow",
                     ["Net cash provided by operating activities",
                      "Net cash used in operating activities"],
                     contains=["operating activities"], required=True)
    fin_cf = resolve(cf, audit, "Financing Cash Flow",
                      ["Net cash provided by financing activities",
                       "Net cash used in financing activities"],
                      contains=["financing activities"])
    net_cash = resolve(cf, audit, "Net Change in Cash",
                        ["NET CASH INCREASE FOR PERIOD", "Net cash increase for period"],
                        contains=["net cash increase"])
    if net_cash.abs().sum() < EPS:
        net_cash = op_cf + inv_cf + fin_cf

    gross_debt = lt_liab + credit_cards
    net_debt = gross_debt - cash

    M["Operating Cash Flow"] = op_cf
    M["Investing Cash Flow"] = inv_cf
    M["Financing Cash Flow"] = fin_cf
    M["Net Change in Cash"] = net_cash
    M["Free Cash Flow"] = op_cf - capex
    M["Gross Debt"] = gross_debt
    M["Net Debt"] = net_debt
    M["Net Debt / EBITDA (x)"] = sdiv(net_debt, ytd_annualised(ebitda))
    M["Gearing (ND/Equity) %"] = sdiv(net_debt, equity.where(equity > 0)) * 100
    M["Interest Cover (x)"] = sdiv(ebit, interest)
    M["OCF / Net Debt %"] = sdiv(ytd_annualised(op_cf), net_debt) * 100

    if (equity <= 0).any():
        bad = [p for p in P if equity[p] <= 0]
        audit.log("WARNING", "Financing Policy",
                   f"Equity is nil or negative in {', '.join(bad)}. Gearing and ROE are not "
                   "meaningful in those months and are suppressed rather than plotted.")

    # ========== STAGE 4 - RETURNS & LEVERAGE EFFECT ==========================
    nopat = ebit * (1 - CFG.TAX_RATE)
    M["NOPAT"] = nopat
    M["ROCE %"] = sdiv(ytd_annualised(nopat), mean_balance(cap_emp)) * 100

    eq_avg = mean_balance(equity)
    ce_avg = mean_balance(cap_emp)
    eq_usable = eq_avg.where((eq_avg > 0) & (eq_avg > CFG.MIN_EQUITY_RATIO * ce_avg.abs()))
    M["ROE %"] = sdiv(ytd_annualised(net_income), eq_usable) * 100
    if eq_usable.isna().any():
        audit.log("WARNING", "Returns",
                   f"ROE suppressed in {int(eq_usable.isna().sum())} of {len(P)} month(s): "
                   "equity is negative or too small relative to capital employed for the ratio "
                   "to mean anything. ROCE is the more meaningful return measure here.")

    M["ROCE . Operating Margin %"] = sdiv(nopat, sales) * 100
    M["ROCE . Capital Turnover (x)"] = sdiv(ytd_annualised(sales), ce_avg)

    i_after_tax = sdiv(ytd_annualised(interest), mean_balance(net_debt)) * (1 - CFG.TAX_RATE) * 100
    M["After-tax Cost of Debt %"] = i_after_tax
    M["Leverage Multiplier (ND/E)"] = sdiv(net_debt, equity.where(equity > 0))
    M["Leverage Effect (pts)"] = (M["ROCE %"] - i_after_tax) * M["Leverage Multiplier (ND/E)"]
    M["ROE (rebuilt) %"] = M["ROCE %"] + M["Leverage Effect (pts)"]

    return M


def run(files: dict, audit: AuditLog):
    """Parse an arbitrary set of uploaded CSVs and build the metrics frame.

    `files` maps a display name -> a file-like object (e.g. Streamlit's
    UploadedFile). Returns (metrics_df, statements, entity_name).
    """
    statements: dict[str, Statement] = {}
    unrecognised = []
    for name, src in files.items():
        try:
            stmt = read_qb(src, name)
        except ParseError as e:
            audit.log("ERROR", "Ingestion", f"{name}: {e}")
            continue
        if stmt.kind == "UNKNOWN":
            unrecognised.append(name)
            audit.log("WARNING", "Ingestion", f"{name}: could not identify statement type — ignored.")
            continue
        if stmt.kind in statements:
            audit.log("WARNING", "Ingestion",
                       f"{name}: another file was already identified as the {stmt.kind} statement — "
                       "this one was ignored.")
            continue
        statements[stmt.kind] = stmt

    missing = {"PL", "BS", "CF"} - set(statements)
    if missing:
        names = {"PL": "Profit & Loss", "BS": "Balance Sheet", "CF": "Statement of Cash Flows"}
        raise ParseError(
            "Missing statement(s): " + ", ".join(names[m] for m in sorted(missing)) +
            ". Upload the P&L, Balance Sheet and Statement of Cash Flows as separate CSVs."
        )

    entity = statements["PL"].entity or "Your Company"
    M = build_engine(statements["PL"], statements["BS"], statements["CF"], audit)
    return M, statements, entity
