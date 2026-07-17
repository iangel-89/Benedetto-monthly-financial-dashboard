# ==============================================================================
# EXECUTIVE SUMMARY TABLE + EXCEL EXPORT
# Structured, numbers-first summary used both for the on-screen "key figures"
# table and as the factual grounding for the AI narrative — the AI is never
# asked to compute anything, only to explain numbers this module already
# computed deterministically.
# ==============================================================================
from __future__ import annotations

import io
import datetime as dt

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


# Native Excel charts per section sheet — each mirrors a dashboard chart.
# (kind, chart title, [metric rows to plot]). Kept single-axis on purpose:
# a chart mixing dollars and a ratio on two scales invents a correlation that
# isn't in the data (same reason the on-screen charts avoid dual axes).
CHART_SPECS = {
    "Wealth Creation": [
        ("bar", "Revenue vs. Net income ($)", ["Sales", "Net Income"]),
        ("line", "Profit margins (% of revenue)",
         ["Gross Margin %", "EBITDA Margin %", "EBIT Margin %", "Net Margin %"]),
    ],
    "Investment Policy": [
        ("bar", "Capital employed ($)", ["Capital Employed"]),
        ("line", "Cash conversion cycle (days)",
         ["DSO (days)", "DIO (days)", "DPO (days)", "Cash Conversion Cycle (days)"]),
        ("line", "Liquidity ratios (x)", ["Current Ratio", "Quick Ratio"]),
    ],
    "Financing Policy": [
        ("bar", "Net debt ($)", ["Net Debt"]),
        ("bar", "Operating cash flow ($)", ["Operating Cash Flow"]),
        ("line", "Net debt / EBITDA (x)", ["Net Debt / EBITDA (x)"]),
    ],
    "Returns & Leverage": [
        ("bar", "ROCE vs. ROE (%)", ["ROCE %", "ROE %"]),
        ("line", "Return vs. cost of debt (%)", ["ROCE %", "After-tax Cost of Debt %"]),
    ],
}


def _fmt_generated() -> str:
    return dt.datetime.now().strftime("%B %d, %Y")


def _write_cover(ws, entity: str, M: pd.DataFrame, has_ai: bool):
    from openpyxl.styles import Font, Alignment

    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 4
    ws.column_dimensions["B"].width = 70

    ws["B2"] = "Financial Health Report"
    ws["B2"].font = Font(bold=True, size=26, color="0B2540")
    ws["B3"] = "Vernimmen four-stage analysis"
    ws["B3"].font = Font(size=12, color="64748B")

    ws["B6"] = entity
    ws["B6"].font = Font(bold=True, size=16, color="0B2540")
    ws["B7"] = f"Period analysed:  {M.index[0]} to {M.index[-1]}   ({len(M.index)} months)"
    ws["B7"].font = Font(size=11, color="52514E")
    ws["B8"] = f"Report generated:  {_fmt_generated()}"
    ws["B8"].font = Font(size=11, color="52514E")

    ws["B11"] = "Contents"
    ws["B11"].font = Font(bold=True, size=13, color="0B2540")

    contents = []
    if has_ai:
        contents.append("AI Summary — plain-English executive narrative")
    contents.append("Executive Summary — key figures and read-across")
    contents += [
        "Wealth Creation — revenue, margins, cost dynamics",
        "Investment Policy — capital employed, working capital, liquidity",
        "Financing Policy — debt, cash flow, leverage",
        "Returns & Leverage — ROCE, ROE, leverage effect",
        "Data Quality Log — assumptions and flags to review",
        "Line Item Mapping — which line in your file fed each figure",
    ]
    r = 12
    for item in contents:
        ws.cell(row=r, column=2, value=f"•  {item}").font = Font(size=11, color="0B2540")
        r += 1

    note_r = r + 2
    ws.cell(row=note_r, column=2,
            value=("Figures are computed deterministically from your uploaded statements. "
                   "The AI narrative only explains those figures — it never invents numbers."
                   if has_ai else
                   "No AI narrative was included in this export. Provide a Gemini API key in the "
                   "app to add a plain-English executive summary.")
            ).font = Font(size=9, italic=True, color="8A8781")


def _write_ai_sheet(ws, ai_summary: str, ai_model: str, entity: str):
    from openpyxl.styles import Font, Alignment

    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 3
    ws.column_dimensions["B"].width = 100

    ws["B2"] = "AI Executive Summary"
    ws["B2"].font = Font(bold=True, size=18, color="0B2540")
    subtitle = entity + (f"   ·   generated by {ai_model}" if ai_model else "")
    ws["B3"] = subtitle
    ws["B3"].font = Font(size=10, color="64748B")

    r = 5
    for raw in ai_summary.split("\n"):
        line = raw.strip()
        if not line:
            r += 1
            continue
        cell = ws.cell(row=r, column=2)
        if line.startswith("####") or line.startswith("###"):
            cell.value = line.lstrip("#").strip()
            cell.font = Font(bold=True, size=12, color="0B2540")
        else:
            cell.value = line.replace("**", "").replace("__", "").replace("*", "")
            cell.font = Font(size=11, color="1a1a1a")
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            ws.row_dimensions[r].height = max(16, 15 * (len(cell.value) // 95 + 1))
        r += 1


def _add_section_charts(ws, cols: list, n_months: int, specs: list):
    """Add native (editable) Excel charts below the transposed data table.

    The data was written with `M[cols].T.to_excel`, so row 1 is the month
    header and metric `cols[i]` sits on row i+2, with col A holding its name
    (used as the series title) and cols B..(1+n_months) holding the values.
    """
    from openpyxl.chart import BarChart, LineChart, Reference

    def metric_row(name):
        return cols.index(name) + 2 if name in cols else None

    cats = Reference(ws, min_col=2, max_col=1 + n_months, min_row=1, max_row=1)
    anchor_row = len(cols) + 4
    for i, (kind, title, metrics) in enumerate(specs):
        rows = [metric_row(m) for m in metrics]
        rows = [r for r in rows if r is not None]
        if not rows:
            continue
        chart = BarChart() if kind == "bar" else LineChart()
        if kind == "bar":
            chart.type = "col"
            chart.gapWidth = 60
        chart.title = title
        chart.height = 7.5
        chart.width = 17
        chart.style = 2
        for r in rows:
            ref = Reference(ws, min_col=1, max_col=1 + n_months, min_row=r, max_row=r)
            chart.add_data(ref, from_rows=True, titles_from_data=True)
        chart.set_categories(cats)
        chart.y_axis.majorGridlines = None
        # Two charts per row of the sheet grid, then wrap.
        col_letter = "B" if i % 2 == 0 else "M"
        row_num = anchor_row + (i // 2) * 16
        ws.add_chart(chart, f"{col_letter}{row_num}")


def export_excel(M: pd.DataFrame, entity: str, statements: dict, audit,
                 ai_summary: str | None = None, ai_model: str | None = None) -> bytes:
    """Build the take-home workbook in memory — no filesystem writes, so this
    works unmodified on Streamlit Cloud.

    Sheet order mirrors the dashboard: Cover, (AI Summary), Executive Summary,
    the four Vernimmen stage sheets (each with native Excel charts), then the
    Data Quality Log and Line Item Mapping. The AI Summary sheet is included
    only when `ai_summary` is provided.
    """
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    buf = io.BytesIO()
    summ = executive_summary(M, entity)
    section_cols = {}

    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        summ.to_excel(xw, sheet_name="Executive Summary", index=False)
        for tab, cols in STAGE_MAP.items():
            cols = [c for c in cols if c in M.columns]
            section_cols[tab] = cols
            M[cols].T.to_excel(xw, sheet_name=tab[:31])
        pd.DataFrame(audit.entries or [{"Severity": "INFO", "Area": "-", "Finding": "No issues raised."}]) \
            .to_excel(xw, sheet_name="Data Quality Log", index=False)
        mapping = pd.DataFrame(
            [{"Statement": k, "Concept": c, "Matched line in your file": v}
             for k, st in statements.items() for c, v in st.resolved.items()])
        mapping.to_excel(xw, sheet_name="Line Item Mapping", index=False)

    buf.seek(0)

    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(buf.getvalue()))
    navy = PatternFill("solid", fgColor="00182B")
    pale = PatternFill("solid", fgColor="F0F6FD")
    thin = Border(bottom=Side(style="thin", color="C1DDF9"))

    data_sheets = list(wb.sheetnames)  # sheets that carry a header row + tables

    # Header + number formatting on the tabular sheets (skip cover/AI, added later).
    for name in data_sheets:
        ws = wb[name]
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

    # Native charts on each stage sheet.
    n_months = len(M.index)
    for tab, specs in CHART_SPECS.items():
        if tab in wb.sheetnames:
            _add_section_charts(wb[tab], section_cols.get(tab, []), n_months, specs)

    # Cover sheet first; AI summary sheet second (when present).
    has_ai = bool(ai_summary and ai_summary.strip())
    cover = wb.create_sheet("Cover", 0)
    _write_cover(cover, entity, M, has_ai)
    if has_ai:
        ai_ws = wb.create_sheet("AI Summary", 1)
        _write_ai_sheet(ai_ws, ai_summary, ai_model or "", entity)

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
