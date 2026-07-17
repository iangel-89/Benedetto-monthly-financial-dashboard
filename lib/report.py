# ==============================================================================
# EXECUTIVE SUMMARY TABLE + EXCEL EXPORT
# Structured, numbers-first summary used both for the on-screen "key figures"
# table and as the factual grounding for the AI narrative — the AI is never
# asked to compute anything, only to explain numbers this module already
# computed deterministically.
# ==============================================================================
from __future__ import annotations

import io

import pandas as pd

from .engine import CFG


def money(v) -> str:
    return "n/a" if pd.isna(v) else f"${v:,.0f}"


def pct(v, dp: int = 1) -> str:
    return "n/a" if pd.isna(v) else f"{v:,.{dp}f}%"


def executive_summary(M: pd.DataFrame, entity: str) -> pd.DataFrame:
    """The one table a CFO (or a Gemini prompt) actually reads: totals, closing
    position, and a plain verdict on each figure."""
    first, last = M.index[0], M.index[-1]
    n = len(M.index)

    flow = lambda c: M[c].sum()
    stock = lambda c: M[c].iloc[-1]

    sales_t, ebitda_t, ebit_t, ni_t = flow("Sales"), flow("EBITDA"), flow("EBIT"), flow("Net Income")
    ocf_t, capex_t = flow("Operating Cash Flow"), flow("Capex")
    nd, eq, ce = stock("Net Debt"), stock("Equity"), stock("Capital Employed")

    roce = M["ROCE %"].iloc[-1]
    roe = M["ROE %"].iloc[-1]
    nd_ebitda = M["Net Debt / EBITDA (x)"].iloc[-1]
    i_rate = M["After-tax Cost of Debt %"].iloc[-1]

    def verdict(ok, good, bad):
        return good if ok else bad

    rows = [
        ("Company", entity, ""),
        ("Period analysed", f"{first} to {last}  ({n} months)", ""),
        ("", "", ""),
        ("-- WEALTH CREATION --", "", ""),
        ("Total revenue", money(sales_t), ""),
        ("Revenue growth, first to last month",
         pct((M['Sales'][last] / M['Sales'][first] - 1) * 100 if abs(M['Sales'][first]) > 1e-9 else float('nan')),
         verdict(M["Sales"][last] >= M["Sales"][first], "Growing", "Shrinking")),
        ("EBITDA (cash operating profit)", money(ebitda_t), f"Margin {pct(ebitda_t / sales_t * 100 if sales_t else float('nan'))}"),
        ("Net income", money(ni_t), f"Margin {pct(ni_t / sales_t * 100 if sales_t else float('nan'))}"),
        ("Costs vs revenue trend",
         f"{M['Scissors Gap (pts)'][last]:+,.0f} pts" if pd.notna(M['Scissors Gap (pts)'][last]) else "n/a",
         verdict(M["Scissors Gap (pts)"][last] >= 0 if pd.notna(M["Scissors Gap (pts)"][last]) else False,
                 "Revenue outgrowing costs", "Costs outgrowing revenue")),
        ("", "", ""),
        ("-- INVESTMENT --", "", ""),
        ("Capital employed (closing)", money(ce), "Net fixed assets + operating working capital"),
        ("Capital spending (capex)", money(capex_t), f"{pct(capex_t / sales_t * 100 if sales_t else float('nan'))} of revenue"),
        ("", "", ""),
        ("-- FINANCING --", "", ""),
        ("Cash from operations", money(ocf_t), verdict(ocf_t > 0, "Self-funding", "Burning cash")),
        ("Free cash flow (after capex)", money(ocf_t - capex_t),
         verdict(ocf_t - capex_t > 0, "Self-financed growth", "Needs external funding")),
        ("Net debt (closing)", money(nd), ""),
        ("Net debt / EBITDA", f"{nd_ebitda:,.2f}x" if pd.notna(nd_ebitda) else "n/a",
         verdict(pd.notna(nd_ebitda) and nd_ebitda < CFG.ND_EBITDA_CEILING,
                 f"Below the {CFG.ND_EBITDA_CEILING:.0f}x caution line",
                 f"Above the {CFG.ND_EBITDA_CEILING:.0f}x caution line")),
        ("Equity (closing)", money(eq), verdict(eq > 0, "Positive", "Negative — solvency risk")),
        ("", "", ""),
        ("-- RETURNS --", "", ""),
        ("Return on capital employed (ROCE)", pct(roce), ""),
        ("Return on equity (ROE)", pct(roe) if pd.notna(roe) else "n/a — equity too thin to measure", ""),
        ("Is debt helping or hurting returns?",
         verdict(pd.notna(roce) and pd.notna(i_rate) and roce > i_rate,
                 "Helping — return beats the cost of debt",
                 "Hurting — cost of debt exceeds the return"), ""),
    ]
    return pd.DataFrame(rows, columns=["Metric", "Value", "Note"])


STAGE_MAP = {
    "Wealth Creation": ["Sales", "COGS", "Gross Profit", "Operating Expenses (core)",
                         "D&A", "EBITDA", "EBIT", "Interest Expense", "Net Income",
                         "Gross Margin %", "EBITDA Margin %", "EBIT Margin %", "Net Margin %",
                         "Sales Growth %", "COGS Growth %", "Opex Growth %"],
    "Investment Policy": ["Fixed Assets", "Operating Working Capital", "Working Capital (CA-CL)",
                           "Capital Employed", "Capex", "Capex / Sales %", "Capex / D&A (x)",
                           "WC Turnover (x)", "WC in Days of Sales", "DSO (days)", "DIO (days)",
                           "DPO (days)", "Cash Conversion Cycle (days)", "Current Ratio", "Quick Ratio"],
    "Financing Policy": ["Operating Cash Flow", "Investing Cash Flow", "Financing Cash Flow",
                          "Free Cash Flow", "Net Change in Cash", "Cash", "Gross Debt", "Net Debt",
                          "Equity", "Net Debt / EBITDA (x)", "Gearing (ND/Equity) %",
                          "Interest Cover (x)", "OCF / Net Debt %"],
    "Returns & Leverage": ["NOPAT", "ROCE %", "ROE %", "After-tax Cost of Debt %",
                            "Leverage Multiplier (ND/E)", "Leverage Effect (pts)"],
}


def export_excel(M: pd.DataFrame, entity: str, statements: dict, audit) -> bytes:
    """Build the downloadable workbook in memory — no filesystem writes, so this
    works unmodified on Streamlit Cloud."""
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    buf = io.BytesIO()
    summ = executive_summary(M, entity)

    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        summ.to_excel(xw, sheet_name="Executive Summary", index=False)
        for tab, cols in STAGE_MAP.items():
            cols = [c for c in cols if c in M.columns]
            M[cols].T.to_excel(xw, sheet_name=tab[:31])
        pd.DataFrame(audit.entries or [{"Severity": "INFO", "Area": "-", "Finding": "No issues raised."}]) \
            .to_excel(xw, sheet_name="Data Quality Log", index=False)
        mapping = pd.DataFrame(
            [{"Statement": k, "Concept": c, "Matched line in your file": v}
             for k, st in statements.items() for c, v in st.resolved.items()])
        mapping.to_excel(xw, sheet_name="Line Item Mapping", index=False)

    buf.seek(0)
    wb_bytes = buf.getvalue()

    # Formatting pass
    buf2 = io.BytesIO(wb_bytes)
    import openpyxl
    wb = openpyxl.load_workbook(buf2)
    navy = PatternFill("solid", fgColor="00182B")
    pale = PatternFill("solid", fgColor="F0F6FD")
    thin = Border(bottom=Side(style="thin", color="C1DDF9"))

    for ws in wb.worksheets:
        ws.freeze_panes = "B2"
        for cell in ws[1]:
            cell.fill = navy
            cell.font = Font(bold=True, color="FFFFFF", size=11)
            cell.alignment = Alignment(horizontal="left", vertical="center")
        ws.row_dimensions[1].height = 22
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.font = Font(size=10)
                cell.border = thin
                if isinstance(cell.value, float):
                    hdr = str(ws.cell(row=cell.row, column=1).value or "")
                    if "%" in hdr or "pts" in hdr:
                        cell.number_format = '#,##0.0"%"'
                    elif "(x)" in hdr or "Ratio" in hdr:
                        cell.number_format = '#,##0.00"x"'
                    elif "days" in hdr.lower():
                        cell.number_format = "#,##0.0"
                    else:
                        cell.number_format = '$#,##0;[Red]($#,##0)'
        for col in ws.columns:
            width = max((len(str(c.value)) for c in col if c.value is not None), default=10)
            ws.column_dimensions[get_column_letter(col[0].column)].width = min(max(width + 2, 12), 52)

    ws = wb["Executive Summary"]
    ws.column_dimensions["A"].width = 40
    ws.column_dimensions["B"].width = 26
    ws.column_dimensions["C"].width = 46
    for row in ws.iter_rows(min_row=2, max_col=1):
        c = row[0]
        if isinstance(c.value, str) and c.value.startswith("--"):
            for cc in ws[c.row]:
                cc.fill = pale
                cc.font = Font(bold=True, color="00182B", size=11)

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
