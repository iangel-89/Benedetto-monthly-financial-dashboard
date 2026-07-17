import io

import streamlit as st

from lib.engine import AuditLog, ParseError, run as run_engine
from lib.report import executive_summary, export_excel
from lib.ai import generate_executive_summary, AIError, MODEL_CANDIDATES
from lib import charts

st.set_page_config(
    page_title="Financial Health Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

NAVY = "#0b2540"
ACCENT = "#f37324"
POS = "#1a8a4a"
NEG = "#c23b34"


# ==============================================================================
# STYLE
# ==============================================================================
def inject_css():
    st.markdown(f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

    html, body, [class*="css"] {{ font-family: 'Inter', sans-serif; }}

    .stApp {{ background-color: #f6f8fb; }}

    section[data-testid="stSidebar"] {{
        background-color: #ffffff;
        border-right: 1px solid #e6ecf3;
    }}

    h1, h2, h3 {{ color: {NAVY}; font-weight: 700; }}

    /* Hero header */
    .app-hero {{
        display: flex; justify-content: space-between; align-items: flex-end;
        padding: 4px 0 18px 0; border-bottom: 1px solid #e2e9f2; margin-bottom: 22px;
    }}
    .app-hero h1 {{ margin: 0; font-size: 1.7rem; }}
    .app-hero .sub {{ color: #64748b; font-size: 0.92rem; margin-top: 4px; }}
    .app-hero .period {{
        text-align: right; color: {NAVY}; font-size: 0.85rem; font-weight: 600;
        background: white; padding: 8px 14px; border-radius: 8px; border: 1px solid #e2e9f2;
    }}

    /* KPI cards */
    .kpi-row {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 22px; }}
    .kpi-card {{
        background: white; border-radius: 12px; padding: 16px 18px;
        border: 1px solid #e6ecf3; box-shadow: 0 1px 2px rgba(11,37,64,0.04);
    }}
    .kpi-label {{ font-size: 0.78rem; color: #64748b; font-weight: 600; text-transform: uppercase; letter-spacing: 0.03em; }}
    .kpi-value {{ font-size: 1.65rem; font-weight: 800; color: {NAVY}; margin-top: 4px; }}
    .kpi-delta {{ font-size: 0.8rem; font-weight: 700; margin-top: 6px; display: inline-block;
                  padding: 2px 8px; border-radius: 999px; }}
    .kpi-delta.up {{ color: {POS}; background: rgba(26,138,74,0.10); }}
    .kpi-delta.down {{ color: {NEG}; background: rgba(194,59,52,0.10); }}
    .kpi-delta.flat {{ color: #64748b; background: #f1f5f9; }}
    .kpi-caption {{ font-size: 0.76rem; color: #94a3b8; margin-top: 6px; }}

    /* Section headers */
    .section-title {{
        font-size: 1.15rem; font-weight: 700; color: {NAVY}; margin: 26px 0 4px 0;
        display: flex; align-items: center; gap: 8px;
    }}
    .section-sub {{ color: #64748b; font-size: 0.86rem; margin-bottom: 14px; }}

    /* Chart card wrapper */
    div[data-testid="stPlotlyChart"] {{
        background: white; border-radius: 12px; border: 1px solid #e6ecf3;
        padding: 6px; box-shadow: 0 1px 2px rgba(11,37,64,0.04);
    }}

    /* AI summary box */
    .ai-tag {{
        font-size: 0.7rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em;
        color: {ACCENT};
    }}
    div[data-testid="stVerticalBlockBorderWrapper"] h4 {{ color: {NAVY}; margin-top: 14px; margin-bottom: 4px; font-size: 0.95rem; }}

    .stButton > button, .stDownloadButton > button {{
        background-color: {ACCENT}; color: white; border: none; border-radius: 6px;
        font-weight: 600; padding: 0.5rem 1.1rem;
    }}
    .stButton > button:hover, .stDownloadButton > button:hover {{
        background-color: #d9651f; color: white;
    }}

    .privacy-note {{
        font-size: 0.78rem; color: #64748b; background: #f1f5f9; border-radius: 8px;
        padding: 10px 12px; margin-top: 14px; line-height: 1.4;
    }}
    </style>
    """, unsafe_allow_html=True)


def kpi_card(label, value, delta_pct=None, caption=""):
    # NOTE: this must be emitted as a single line with no leading whitespace.
    # st.markdown() runs CommonMark first — a blank line followed by an
    # indented line (as a pretty-printed multi-line f-string would produce
    # once several cards are concatenated) is parsed as a *code block*, not
    # passed through as HTML, so only the first card would render.
    if delta_pct is None or delta_pct != delta_pct:  # NaN check
        delta_html = ""
    else:
        direction = "up" if delta_pct > 0.05 else ("down" if delta_pct < -0.05 else "flat")
        arrow = "▲" if direction == "up" else ("▼" if direction == "down" else "▪")
        delta_html = f'<div class="kpi-delta {direction}">{arrow} {abs(delta_pct):.1f}% vs prior month</div>'
    return (f'<div class="kpi-card"><div class="kpi-label">{label}</div>'
            f'<div class="kpi-value">{value}</div>{delta_html}'
            f'<div class="kpi-caption">{caption}</div></div>')


def money0(v):
    if v != v:
        return "n/a"
    sign = "-" if v < 0 else ""
    return f"{sign}${abs(v):,.0f}"


def summary_key(M, entity):
    """A stable fingerprint of the current dataset, so cached AI text and the
    built workbook are only reused for the data they were made from."""
    return (entity, tuple(M.index), round(float(M["Sales"].sum()), 2))


# ==============================================================================
# DATA PROCESSING (cached so UI interactions don't re-parse the CSVs)
# ==============================================================================
@st.cache_data(show_spinner=False)
def process_files(file_bytes: dict):
    audit = AuditLog()
    files = {name: io.BytesIO(b) for name, b in file_bytes.items()}
    try:
        M, statements, entity = run_engine(files, audit)
    except ParseError as e:
        e.audit_entries = audit.entries
        raise
    return M, statements, entity, audit


# ==============================================================================
# SIDEBAR
# ==============================================================================
def sidebar():
    st.sidebar.markdown(f"<h2 style='color:{NAVY};margin-bottom:0;'>📊 Sky & Aarons</h2>", unsafe_allow_html=True)
    st.sidebar.caption("Financial Health Dashboard")
    st.sidebar.divider()

    st.sidebar.subheader("1. Upload your financials")
    uploaded = st.sidebar.file_uploader(
        "QuickBooks CSV exports",
        type="csv",
        accept_multiple_files=True,
        help="Upload all three: Profit & Loss, Balance Sheet, and Statement of Cash Flows. "
             "File names don't matter — they're identified automatically by content.",
    )
    with st.sidebar.expander("Where do I get these from QuickBooks?"):
        st.markdown(
            "1. Go to **Reports** in QuickBooks Online.\n"
            "2. Open **Profit and Loss**, **Balance Sheet**, and **Statement of Cash Flows**.\n"
            "3. Set the same monthly date range on all three.\n"
            "4. Click **Export → Export to CSV** on each, then upload all three here."
        )

    st.sidebar.subheader("2. AI executive summary")
    try:
        default_key = st.secrets["GEMINI_API_KEY"]
    except (KeyError, FileNotFoundError):
        default_key = ""
    api_key = st.sidebar.text_input(
        "Gemini API key", value="", type="password",
        placeholder="Using saved key" if default_key else "Paste your Gemini API key",
        help="Get a free key at aistudio.google.com/apikey. Stored only for this browser session.",
    ) or default_key
    model_override = ""
    with st.sidebar.expander("Advanced AI settings"):
        model_override = st.text_input(
            "Model override (optional)", value="",
            placeholder=f"default tries: {', '.join(MODEL_CANDIDATES)}",
        )

    st.sidebar.markdown(
        '<div class="privacy-note">🔒 Nothing you upload is saved or written to a database — '
        "the numbers are processed in memory for this session and vanish when you refresh or "
        "close the tab. Your Gemini key is only used to call Google's API directly from this "
        "session.</div>",
        unsafe_allow_html=True,
    )
    return uploaded, api_key, model_override


# ==============================================================================
# MAIN
# ==============================================================================
def main():
    inject_css()
    uploaded, api_key, model_override = sidebar()

    st.markdown(f"""
    <div class="app-hero">
        <div>
            <h1>Financial Health Dashboard</h1>
            <div class="sub">A plain-English read on how the business is really doing.</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    if not uploaded or len(uploaded) < 3:
        st.info(
            "👋 Upload your **Profit & Loss**, **Balance Sheet**, and **Statement of Cash Flows** "
            "CSV exports in the sidebar to get started. All three are needed — file names don't matter."
        )
        st.stop()

    file_bytes = {f.name: f.getvalue() for f in uploaded}
    try:
        with st.spinner("Reading your financial statements…"):
            M, statements, entity, audit = process_files(file_bytes)
    except ParseError as e:
        st.error(f"⚠️ {e}")
        entries = getattr(e, "audit_entries", [])
        if entries:
            with st.expander("What we found while reading your files"):
                for a in entries:
                    icon = {"ERROR": "🔴", "WARNING": "🟡", "INFO": "🔵"}.get(a["Severity"], "•")
                    st.markdown(f"{icon} **[{a['Area']}]** {a['Finding']}")
        st.stop()

    period = f"{M.index[0]} → {M.index[-1]}"
    st.markdown(f"""
    <div style="margin-top:-14px;margin-bottom:18px;">
        <span style="font-weight:700;color:{NAVY};font-size:1.05rem;">{entity}</span>
        <span style="color:#94a3b8;"> · {period} · {len(M.index)} months</span>
    </div>
    """, unsafe_allow_html=True)

    errors = audit.errors()
    if errors:
        with st.expander(f"⚠️ {len(errors)} data quality issue(s) found — click to review", expanded=False):
            for a in errors:
                st.warning(f"**{a['Area']}:** {a['Finding']}")

    # ---- KPI row ----
    latest = M.index[-1]
    sales_delta = M["Sales Growth %"].iloc[-1]
    ni_series = M["Net Income"]
    ni_delta = ((ni_series.iloc[-1] - ni_series.iloc[-2]) / abs(ni_series.iloc[-2]) * 100
                if len(ni_series) > 1 and abs(ni_series.iloc[-2]) > 1e-9 else float("nan"))
    cash_series = M["Cash"]
    cash_delta = ((cash_series.iloc[-1] - cash_series.iloc[-2]) / abs(cash_series.iloc[-2]) * 100
                  if len(cash_series) > 1 and abs(cash_series.iloc[-2]) > 1e-9 else float("nan"))
    ocf_series = M["Operating Cash Flow"]
    ocf_delta = ((ocf_series.iloc[-1] - ocf_series.iloc[-2]) / abs(ocf_series.iloc[-2]) * 100
                 if len(ocf_series) > 1 and abs(ocf_series.iloc[-2]) > 1e-9 else float("nan"))

    st.markdown('<div class="kpi-row">' + "".join([
        kpi_card("Revenue", money0(M["Sales"].iloc[-1]), sales_delta, f"Money brought in during {latest}"),
        kpi_card("Profit", money0(M["Net Income"].iloc[-1]), ni_delta, f"What's left after all costs in {latest}"),
        kpi_card("Cash on Hand", money0(M["Cash"].iloc[-1]), cash_delta, "Cash sitting in the bank right now"),
        kpi_card("Cash From Operations", money0(M["Operating Cash Flow"].iloc[-1]), ocf_delta,
                  "Cash actually generated by running the business"),
    ]) + '</div>', unsafe_allow_html=True)

    view = st.radio("View", ["Simple", "Detailed"], horizontal=True, label_visibility="collapsed")

    if view == "Simple":
        render_simple(M)
    else:
        render_detailed(M, statements, entity, audit, api_key, model_override)

    render_ai_section(M, entity, audit, api_key, model_override)

    st.divider()
    st.caption("Sky & Aarons Accountancy LLP · Built on the Vernimmen four-stage financial framework "
               "(Wealth Creation → Investment → Financing → Returns).")


def render_simple(M):
    st.plotly_chart(charts.simple_health_meters(M), width='stretch', config={"displayModeBar": False})

    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(charts.simple_revenue_profit(M), width='stretch', config={"displayModeBar": False})
    with c2:
        st.plotly_chart(charts.simple_cash_trend(M), width='stretch', config={"displayModeBar": False})

    st.plotly_chart(charts.simple_revenue_bridge(M), width='stretch', config={"displayModeBar": False})


def render_take_home(M, statements, entity, audit, api_key, model_override):
    """The 'bring it home' deliverable: one Excel workbook mirroring the
    dashboard's sections, with native charts and — when possible — the AI
    executive summary.

    The summary is reused if it was already generated on screen; otherwise, if
    a Gemini key is available, it's generated on the fly at build time so the
    take-home file is complete. Building is behind a button so Gemini is never
    called on every rerun, and the bytes are cached in session state.
    """
    key = summary_key(M, entity)
    st.markdown('<div class="section-sub">📥 <b>Take-home report</b> — one Excel file with every '
                'section, editable charts, and (if a Gemini key is set) the AI summary.</div>',
                unsafe_allow_html=True)

    if st.button("🧾 Build Excel report"):
        with st.spinner("Building your report…"):
            ai_text = ai_model = note = None
            if st.session_state.get("ai_summary_key") == key and st.session_state.get("ai_summary_text"):
                ai_text = st.session_state["ai_summary_text"]
                ai_model = st.session_state.get("ai_summary_model")
            elif api_key:
                try:
                    ai_text, ai_model = generate_executive_summary(
                        api_key, M, entity, audit.entries, model_override=(model_override or "").strip()
                    )
                    # Cache it so the on-screen AI section shows the same text.
                    st.session_state["ai_summary_text"] = ai_text
                    st.session_state["ai_summary_model"] = ai_model
                    st.session_state["ai_summary_key"] = key
                except AIError as e:
                    note = (f"AI summary couldn't be generated ({e.friendly}). "
                            "The report was built with the numbers-based summary only.")
            else:
                note = ("No Gemini key set, so the report has the numbers-based summary only. "
                        "Add a key in the sidebar and rebuild to include the AI narrative.")

            xlsx = export_excel(M, entity, statements, audit, ai_summary=ai_text, ai_model=ai_model)
            st.session_state["xlsx_bytes"] = xlsx
            st.session_state["xlsx_key"] = key
            st.session_state["xlsx_has_ai"] = bool(ai_text)
            st.session_state["xlsx_note"] = note

    if st.session_state.get("xlsx_bytes") and st.session_state.get("xlsx_key") == key:
        if st.session_state.get("xlsx_note"):
            st.info(st.session_state["xlsx_note"])
        badge = "with AI summary" if st.session_state.get("xlsx_has_ai") else "numbers summary only"
        st.download_button(
            f"⬇ Download Excel report ({badge})",
            data=st.session_state["xlsx_bytes"],
            file_name=f"{entity.replace(' ', '_')}_Financial_Report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


def render_detailed(M, statements, entity, audit, api_key, model_override):
    st.markdown('<div class="section-title">Executive Summary</div>', unsafe_allow_html=True)
    summ = executive_summary(M, entity)
    st.dataframe(summ, hide_index=True, width='stretch')

    render_take_home(M, statements, entity, audit, api_key, model_override)

    tabs = st.tabs(["1 · Wealth Creation", "2 · Investment Policy", "3 · Financing Policy",
                     "4 · Returns", "Data Quality & Mapping"])

    with tabs[0]:
        st.caption("How much money the business makes, and whether revenue is growing faster than costs.")
        c1, c2 = st.columns(2)
        with c1:
            st.plotly_chart(charts.detail_revenue_momentum(M), width='stretch', config={"displayModeBar": False})
        with c2:
            st.plotly_chart(charts.detail_scissors(M), width='stretch', config={"displayModeBar": False})
        c3, c4 = st.columns(2)
        with c3:
            st.plotly_chart(charts.detail_common_size(M), width='stretch', config={"displayModeBar": False})
        with c4:
            st.plotly_chart(charts.detail_variance(M), width='stretch', config={"displayModeBar": False})
        st.plotly_chart(charts.detail_margin_walk(M), width='stretch', config={"displayModeBar": False})

    with tabs[1]:
        st.caption("What the business owns, what it owes short-term, and how efficiently cash cycles through operations.")
        c1, c2 = st.columns(2)
        with c1:
            st.plotly_chart(charts.detail_capital_employed(M), width='stretch', config={"displayModeBar": False})
        with c2:
            st.plotly_chart(charts.detail_working_capital(M), width='stretch', config={"displayModeBar": False})
        st.plotly_chart(charts.detail_cash_conversion_cycle(M), width='stretch', config={"displayModeBar": False})
        st.plotly_chart(charts.detail_capex_da(M), width='stretch', config={"displayModeBar": False})

    with tabs[2]:
        st.caption("How the business is funded — debt, cash, and where cash flow ultimately goes.")
        c1, c2 = st.columns(2)
        with c1:
            st.plotly_chart(charts.detail_net_debt(M), width='stretch', config={"displayModeBar": False})
        with c2:
            st.plotly_chart(charts.detail_leverage(M), width='stretch', config={"displayModeBar": False})
        st.plotly_chart(charts.detail_operating_cf(M), width='stretch', config={"displayModeBar": False})
        st.plotly_chart(charts.detail_cf_allocation(M), width='stretch', config={"displayModeBar": False})

    with tabs[3]:
        st.caption("Whether the business is generating good returns on the money invested in it, and whether debt is helping or hurting.")
        st.plotly_chart(charts.detail_returns(M), width='stretch', config={"displayModeBar": False})

    with tabs[4]:
        st.markdown("**Data quality flags**")
        if audit.entries:
            for a in audit.entries:
                icon = {"ERROR": "🔴", "WARNING": "🟡", "INFO": "🔵"}.get(a["Severity"], "•")
                st.markdown(f"{icon} **[{a['Area']}]** {a['Finding']}")
        else:
            st.success("No issues found.")
        st.markdown("**Line-item mapping** — which line in your file each figure came from")
        for kind, label in [("PL", "Profit & Loss"), ("BS", "Balance Sheet"), ("CF", "Statement of Cash Flows")]:
            if kind in statements:
                st.caption(label)
                mapping = statements[kind].resolved
                st.table({"Concept": list(mapping.keys()), "Matched line": list(mapping.values())})


def render_ai_section(M, entity, audit, api_key, model_override):
    st.markdown('<div class="section-title">🤖 AI Executive Summary</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">A plain-English narrative generated by Google Gemini, grounded only in the figures above.</div>',
                unsafe_allow_html=True)

    cache_key = summary_key(M, entity)
    if st.session_state.get("ai_summary_key") != cache_key:
        st.session_state.pop("ai_summary_text", None)

    col1, col2 = st.columns([1, 5])
    with col1:
        generate = st.button("✨ Generate summary")
    if generate:
        if not api_key:
            st.error("Add your Gemini API key in the sidebar first.")
        else:
            with st.spinner("Analyzing the numbers…"):
                try:
                    text, model_used = generate_executive_summary(
                        api_key, M, entity, audit.entries, model_override=model_override.strip()
                    )
                    st.session_state["ai_summary_text"] = text
                    st.session_state["ai_summary_model"] = model_used
                    st.session_state["ai_summary_key"] = cache_key
                except AIError as e:
                    st.error(f"Couldn't generate a summary: {e.friendly}")
                    if e.technical and e.technical != e.friendly:
                        with st.expander("Technical details"):
                            st.code(e.technical)

    if st.session_state.get("ai_summary_text") and st.session_state.get("ai_summary_key") == cache_key:
        with st.container(border=True):
            st.markdown(
                f'<span class="ai-tag">✨ Generated by {st.session_state.get("ai_summary_model", "Gemini")}</span>',
                unsafe_allow_html=True,
            )
            st.markdown(st.session_state["ai_summary_text"])


if __name__ == "__main__":
    main()
