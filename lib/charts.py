# ==============================================================================
# CHARTS — two tiers:
#   simple_*   for someone with zero finance background (the default view)
#   detail_*   the full Vernimmen four-stage breakdown (opt-in "Detailed" view)
#
# Every chart here uses exactly ONE y-axis. The original engine leaned on
# dual-axis combo charts (bar + line on two different scales) which invent a
# visual correlation that isn't in the data — see dataviz anti-patterns. Where
# the source chart paired two differently-scaled series, it's split into two
# single-axis charts here instead.
# ==============================================================================
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .engine import CFG, sdiv
from .theme import (
    NAVY, BLUE_DEEP, BLUE_MID, BLUE_SOFT, BLUE_PALE, POS, NEG, WARN, GREY,
    brand_layout, trend_colors, status_color,
)
from .report import money, pct


def _fmt_money_short(v: float) -> str:
    if pd.isna(v):
        return "n/a"
    a = abs(v)
    sign = "-" if v < 0 else ""
    if a >= 1_000_000:
        return f"{sign}${a / 1_000_000:,.1f}M"
    if a >= 1_000:
        return f"{sign}${a / 1_000:,.0f}K"
    return f"{sign}${a:,.0f}"


# ==============================================================================
# SIMPLE VIEW — plain language, minimal chart types, one clear takeaway each
# ==============================================================================
def simple_revenue_profit(M: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_bar(x=M.index, y=M["Sales"], name="Revenue", marker_color=BLUE_PALE,
                text=[_fmt_money_short(v) for v in M["Sales"]], textposition="outside",
                textfont=dict(size=10, color=GREY))
    fig.add_scatter(x=M.index, y=M["Net Income"], name="Profit you kept",
                     mode="lines+markers", line=dict(color=NAVY, width=3),
                     marker=dict(size=9, line=dict(color="white", width=2)))
    fig.update_yaxes(title_text="$ per month", tickprefix="$", tickformat=",.0f")
    brand_layout(fig, "Revenue vs. Profit",
                 "The tall bars are money coming in. The dark line is what's actually left after costs.")
    return fig


def simple_revenue_bridge(M: pd.DataFrame) -> go.Figure:
    cogs_t = M["COGS"].sum()
    opex_t = M["Operating Expenses (core)"].sum() + M["Interest Expense"].sum() + M["D&A"].sum()
    sales_t = M["Sales"].sum()
    profit_t = M["Net Income"].sum()
    other_t = sales_t - cogs_t - opex_t - profit_t  # taxes, other income/expense, rounding

    labels = ["Revenue", "Cost of goods sold", "Operating costs"]
    values = [sales_t, -cogs_t, -opex_t]
    measures = ["absolute", "relative", "relative"]
    if abs(other_t) > max(1.0, 0.005 * sales_t):
        labels.append("Other (taxes, misc.)")
        values.append(-other_t)
        measures.append("relative")
    labels.append("Profit you kept")
    values.append(0)
    measures.append("total")

    end_color = POS if profit_t >= 0 else NEG
    fig = go.Figure(go.Waterfall(
        orientation="v", measure=measures, x=labels, y=values,
        text=[_fmt_money_short(v) for v in
              [sales_t, -cogs_t, -opex_t] + ([-other_t] if len(labels) == 5 else []) + [profit_t]],
        textposition="outside",
        connector=dict(line=dict(color=BLUE_SOFT, dash="dot")),
        increasing=dict(marker=dict(color=BLUE_DEEP)),
        decreasing=dict(marker=dict(color=BLUE_MID)),
        totals=dict(marker=dict(color=end_color)),
    ))
    fig.update_yaxes(title_text="$", tickprefix="$", tickformat=",.0f")
    brand_layout(fig, "Where Your Revenue Went",
                 "Every dollar in, and where it ended up, over the whole period.")
    return fig


def simple_cash_trend(M: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_scatter(x=M.index, y=M["Cash"], mode="lines+markers", name="Cash on hand",
                     line=dict(color=BLUE_DEEP, width=3), fill="tozeroy",
                     fillcolor="rgba(28,78,128,0.10)",
                     marker=dict(size=8, line=dict(color="white", width=2)))
    fig.update_yaxes(title_text="Cash in the bank", tickprefix="$", tickformat=",.0f")
    brand_layout(fig, "Cash in the Bank, Over Time",
                 "Your actual cash balance at the end of each month.")
    return fig


def _gauge(value, title, caption, rng, bands, threshold=None, suffix="", fmt=".2f"):
    value = 0.0 if pd.isna(value) else float(value)
    steps = [dict(range=[a, b], color=c) for a, b, c in bands]
    gauge = dict(
        axis=dict(range=rng, tickcolor=GREY, tickfont=dict(color=GREY, size=10)),
        bar=dict(color=NAVY, thickness=0.28),
        bgcolor="white", borderwidth=1, bordercolor=BLUE_PALE,
        steps=steps,
    )
    if threshold is not None:
        gauge["threshold"] = dict(line=dict(color=NAVY, width=4), thickness=0.85, value=threshold)
    return go.Indicator(
        mode="gauge+number", value=value,
        number=dict(valueformat=fmt, suffix=suffix, font=dict(size=36, color=NAVY)),
        title=dict(text=f"<b>{title}</b><br><span style='font-size:11px;color:{GREY}'>{caption}</span>",
                   font=dict(size=13, color=NAVY)),
        gauge=gauge,
    )


def simple_health_meters(M: pd.DataFrame) -> go.Figure:
    from plotly.subplots import make_subplots
    p = M.index[-1]
    cr = M["Current Ratio"][p]
    qr = M["Quick Ratio"][p]
    nde = M["Net Debt / EBITDA (x)"][p]

    fig = make_subplots(rows=1, cols=3, specs=[[{"type": "indicator"}] * 3])
    fig.add_trace(_gauge(cr, "Bills Coverage", "Cash + near-cash ÷ short-term bills",
                          [0, 3], [(0, 1, NEG), (1, 1.5, WARN), (1.5, 3, POS)],
                          threshold=CFG.CURRENT_RATIO_MIN), row=1, col=1)
    fig.add_trace(_gauge(qr, "Cash Cushion", "Same, without counting inventory",
                          [0, 2], [(0, 0.5, NEG), (0.5, 1, WARN), (1, 2, POS)],
                          threshold=CFG.QUICK_RATIO_MIN), row=1, col=2)
    nde_val = 0 if pd.isna(nde) else nde
    fig.add_trace(_gauge(nde_val, "Debt Load", "Years of profit to pay off debt",
                          [0, 6], [(0, 2, POS), (2, 3, WARN), (3, 6, NEG)],
                          threshold=CFG.ND_EBITDA_CEILING, suffix="x"), row=1, col=3)
    brand_layout(fig, "Financial Health Check",
                 f"As of {p}. Green = healthy, amber = keep an eye on it, red = needs attention.",
                 height=340)
    return fig


# ==============================================================================
# DETAILED VIEW — full Vernimmen four-stage breakdown
# ==============================================================================
def detail_revenue_momentum(M: pd.DataFrame) -> go.Figure:
    colors = trend_colors(M["Sales Growth %"])
    hover = [f"{g:+.1f}% vs prior month" if pd.notna(g) else "first month" for g in M["Sales Growth %"]]
    fig = go.Figure()
    fig.add_bar(x=M.index, y=M["Sales"], marker_color=colors, name="Revenue",
                text=[_fmt_money_short(v) for v in M["Sales"]], textposition="outside",
                textfont=dict(size=10, color=GREY),
                customdata=hover, hovertemplate="%{x}<br>%{y:$,.0f}<br>%{customdata}<extra></extra>")
    fig.update_yaxes(title_text="Revenue", tickprefix="$", tickformat=",.0f")
    brand_layout(fig, "Wealth Creation · Revenue Momentum",
                 f"Bars turn green/red when month-over-month growth passes ±{CFG.TREND_THRESHOLD:.0%}.")
    return fig


def detail_scissors(M: pd.DataFrame) -> go.Figure:
    gap = M["Scissors Gap (pts)"].iloc[-1]
    gap_fill = "rgba(26,138,74,0.12)" if pd.notna(gap) and gap >= 0 else "rgba(194,59,52,0.12)"
    fig = go.Figure()
    fig.add_scatter(x=M.index, y=M["Sales Index (100)"], name="Revenue (indexed)",
                     mode="lines+markers", line=dict(color=NAVY, width=3))
    fig.add_scatter(x=M.index, y=M["Cost Base Index (100)"], name="Total costs (indexed)",
                     mode="lines+markers", line=dict(color=BLUE_MID, width=3, dash="dash"),
                     fill="tonexty", fillcolor=gap_fill)
    fig.add_hline(y=100, line=dict(color=GREY, dash="dot"))
    fig.update_yaxes(title_text=f"Index ({M.index[0]} = 100)")
    brand_layout(fig, "Wealth Creation · Revenue vs. Cost Growth",
                 "Both lines start at 100. When revenue (solid) pulls above costs (dashed), margins widen.")
    return fig


def detail_margin_walk(M: pd.DataFrame) -> go.Figure:
    p = M.index[-1]
    labels = ["Revenue", "COGS", "Gross Profit", "Operating Expenses", "EBITDA", "D&A", "EBIT"]
    vals = [M["Sales"][p], -M["COGS"][p], 0, -M["Operating Expenses (core)"][p], 0, -M["D&A"][p], 0]
    measures = ["absolute", "relative", "total", "relative", "total", "relative", "total"]
    text = [money(M["Sales"][p]), money(-M["COGS"][p]), money(M["Gross Profit"][p]),
            money(-M["Operating Expenses (core)"][p]), money(M["EBITDA"][p]),
            money(-M["D&A"][p]), money(M["EBIT"][p])]
    fig = go.Figure(go.Waterfall(
        orientation="v", measure=measures, x=labels, y=vals, text=text, textposition="outside",
        connector=dict(line=dict(color=BLUE_SOFT, dash="dot")),
        increasing=dict(marker=dict(color=BLUE_DEEP)),
        decreasing=dict(marker=dict(color=BLUE_SOFT)),
        totals=dict(marker=dict(color=NAVY)),
    ))
    fig.update_yaxes(tickprefix="$", tickformat=",.0f")
    brand_layout(fig, f"Wealth Creation · Margin Walk — {p}",
                 f"EBIT margin {M['EBIT Margin %'][p]:.1f}%. Interest is treated as a financing cost, not an operating one.")
    return fig


def detail_common_size(M: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    for name, col, color in [("COGS % of revenue", "COGS", BLUE_DEEP),
                              ("Opex % of revenue", "Operating Expenses (core)", BLUE_MID),
                              ("EBIT margin %", "EBIT", BLUE_PALE)]:
        share = sdiv(M[col], M["Sales"]) * 100
        fig.add_bar(x=M.index, y=share, name=name, marker_color=color,
                     text=[pct(v, 0) for v in share], textposition="inside",
                     insidetextfont=dict(color="white" if color != BLUE_PALE else NAVY))
    fig.update_layout(barmode="stack")
    fig.update_yaxes(title_text="% of revenue", ticksuffix="%")
    brand_layout(fig, "Wealth Creation · Where Every Revenue Dollar Goes",
                 "A rising COGS band eats into margin from below.")
    return fig


def detail_variance(M: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    for name, col, color in [("Revenue", "Sales Growth %", NAVY),
                              ("COGS", "COGS Growth %", BLUE_MID),
                              ("Opex", "Opex Growth %", BLUE_SOFT)]:
        d = M[col].iloc[1:]
        fig.add_bar(x=d.index, y=d, name=name, marker_color=color,
                     text=[pct(v) for v in d], textposition="outside")
    fig.update_layout(barmode="group")
    for lvl in (CFG.TREND_THRESHOLD * 100, -CFG.TREND_THRESHOLD * 100):
        fig.add_hline(y=lvl, line=dict(color=GREY, dash="dot", width=1))
    fig.add_hline(y=0, line=dict(color=NAVY, width=1.5))
    fig.update_yaxes(title_text="Month-over-month change", ticksuffix="%")
    brand_layout(fig, "Wealth Creation · Month-over-Month Variance",
                 f"Dotted lines mark the ±{CFG.TREND_THRESHOLD:.0%} materiality threshold.")
    return fig


def detail_capital_employed(M: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_bar(x=M.index, y=M["Capital Employed"], name="Capital employed", marker_color=BLUE_DEEP,
                text=[_fmt_money_short(v) for v in M["Capital Employed"]], textposition="outside")
    fig.update_yaxes(title_text="Capital employed", tickprefix="$", tickformat=",.0f")
    brand_layout(fig, "Investment Policy · Capital Employed",
                 "Net fixed assets + operating working capital — what the business needs financing for.")
    return fig


def detail_working_capital(M: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_scatter(x=M.index, y=M["Operating Working Capital"], name="Operating working capital",
                     mode="lines+markers", line=dict(color=NAVY, width=3),
                     marker=dict(symbol="diamond", size=9))
    fig.add_scatter(x=M.index, y=M["Working Capital (CA-CL)"], name="Accounting working capital (CA − CL)",
                     mode="lines+markers", line=dict(color=BLUE_MID, width=2, dash="dot"))
    fig.update_yaxes(title_text="$", tickprefix="$", tickformat=",.0f")
    brand_layout(fig, "Investment Policy · Working Capital",
                 "Operating WC = receivables + inventory − payables. A gap to the accounting figure usually means non-operating balances are mixed in.")
    return fig


def detail_cash_conversion_cycle(M: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    for name, col, color, dash in [("Days to collect (DSO)", "DSO (days)", NAVY, "solid"),
                                    ("Days of inventory (DIO)", "DIO (days)", BLUE_MID, "solid"),
                                    ("Days to pay suppliers (DPO)", "DPO (days)", BLUE_SOFT, "dash"),
                                    ("Full cash cycle", "Cash Conversion Cycle (days)", BLUE_DEEP, "solid")]:
        fig.add_scatter(x=M.index, y=M[col], name=name, mode="lines+markers",
                         line=dict(color=color, width=3.5 if "cycle" in name.lower() else 2.2, dash=dash))
    fig.update_yaxes(title_text="Days")
    brand_layout(fig, "Investment Policy · Cash Conversion Cycle",
                 "How many days of sales are tied up between paying suppliers and collecting from customers.")
    return fig


def detail_capex_da(M: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_bar(x=M.index, y=M["Capex"], name="Capital spending (capex)", marker_color=BLUE_DEEP,
                text=[_fmt_money_short(v) for v in M["Capex"]], textposition="outside")
    fig.add_bar(x=M.index, y=M["D&A"], name="Depreciation (D&A)", marker_color=BLUE_PALE)
    fig.update_layout(barmode="group")
    fig.update_yaxes(title_text="$", tickprefix="$", tickformat=",.0f")
    brand_layout(fig, "Investment Policy · Capex vs. Depreciation",
                 "Capex above D&A means the business is investing for growth, not just maintaining what it has.")
    return fig


def detail_operating_cf(M: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    colors = [POS if v >= 0 else NEG for v in M["Operating Cash Flow"]]
    fig.add_bar(x=M.index, y=M["Operating Cash Flow"], marker_color=colors, name="Operating cash flow",
                text=[_fmt_money_short(v) for v in M["Operating Cash Flow"]], textposition="outside")
    fig.add_hline(y=0, line=dict(color=NAVY, width=1.5))
    fig.update_yaxes(title_text="$", tickprefix="$", tickformat=",.0f")
    brand_layout(fig, "Financing Policy · Cash Generated by Operations",
                 "Green months funded themselves; red months burned cash from reserves or financing.")
    return fig


def detail_net_debt(M: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_bar(x=M.index, y=M["Net Debt"], name="Net debt", marker_color=BLUE_DEEP,
                text=[_fmt_money_short(v) for v in M["Net Debt"]], textposition="outside")
    fig.add_hline(y=0, line=dict(color=NAVY, width=1.5))
    fig.update_yaxes(title_text="Net debt (debt minus cash)", tickprefix="$", tickformat=",.0f")
    brand_layout(fig, "Financing Policy · Net Debt",
                 "Below zero means the business holds more cash than interest-bearing debt.")
    return fig


def detail_leverage(M: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_scatter(x=M.index, y=M["Net Debt / EBITDA (x)"], name="Net debt ÷ EBITDA (annualised)",
                     mode="lines+markers", line=dict(color=NAVY, width=3), marker=dict(size=9))
    fig.add_hline(y=CFG.ND_EBITDA_CEILING, line=dict(color=NEG, dash="dash", width=2),
                  annotation_text=f" Caution line: {CFG.ND_EBITDA_CEILING:.1f}x", annotation_font=dict(color=NEG))
    fig.update_yaxes(title_text="x EBITDA", ticksuffix="x")
    brand_layout(fig, "Financing Policy · Leverage Trend",
                 "How many years of EBITDA it would take to pay off net debt. Lower is safer.")
    return fig


def detail_cf_allocation(M: pd.DataFrame) -> go.Figure:
    ocf, capex = M["Operating Cash Flow"].sum(), M["Capex"].sum()
    fin, net = M["Financing Cash Flow"].sum(), M["Net Change in Cash"].sum()
    fig = go.Figure(go.Waterfall(
        orientation="v",
        measure=["absolute", "relative", "total", "relative", "total"],
        x=["Cash from operations", "Capex", "Free cash flow", "Financing (debt + owner draws)", "Net change in cash"],
        y=[ocf, -capex, 0, fin, 0],
        text=[money(v) for v in [ocf, -capex, ocf - capex, fin, net]], textposition="outside",
        connector=dict(line=dict(color=BLUE_SOFT, dash="dot")),
        increasing=dict(marker=dict(color=BLUE_DEEP)),
        decreasing=dict(marker=dict(color=BLUE_SOFT)),
        totals=dict(marker=dict(color=NAVY)),
    ))
    fig.update_yaxes(tickprefix="$", tickformat=",.0f")
    brand_layout(fig, f"Financing Policy · Where Cash Flow Went — {M.index[0]} to {M.index[-1]}",
                 "Where the cash generated by the business actually ended up.")
    return fig


def detail_returns(M: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_bar(x=M.index, y=M["ROCE %"], name="Return on capital employed", marker_color=NAVY,
                text=[pct(v, 0) for v in M["ROCE %"]], textposition="outside")
    fig.add_bar(x=M.index, y=M["ROE %"], name="Return on equity", marker_color=BLUE_SOFT,
                text=[pct(v, 0) if pd.notna(v) else "n/a" for v in M["ROE %"]], textposition="outside")
    fig.add_scatter(x=M.index, y=M["After-tax Cost of Debt %"], name="Cost of debt",
                     mode="lines+markers", line=dict(color=NEG, width=2.5, dash="dash"))
    fig.update_layout(barmode="group")
    fig.update_yaxes(title_text="Annualised return", ticksuffix="%")
    last = M["ROCE %"].iloc[-1]
    i_last = M["After-tax Cost of Debt %"].iloc[-1]
    verdict = ("Debt is creating value (return beats its cost)" if pd.notna(last) and pd.notna(i_last) and last > i_last
               else "Debt is diluting returns (cost exceeds the return)")
    brand_layout(fig, "Returns · ROCE vs. ROE vs. Cost of Debt", verdict)
    return fig
