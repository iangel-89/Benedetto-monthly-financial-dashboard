import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import google.generativeai as genai
import io
import re
import numpy as np

# ==========================================
# CONFIGURATION & BRANDING
# ==========================================
st.set_page_config(page_title="Financial Analytics & Vernimmen Plan", layout="wide")

COLORS = {
    "dark_blue": "#00182b",
    "blue_1": "#6e9fc8",
    "blue_2": "#92c1ed",
    "blue_3": "#c1ddf9",
    "light_blue": "#f0f6fd",
    "positive": "#72b043",
    "negative": "#e12729",
    "accent": "#f37324"
}

def inject_custom_css():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&family=JetBrains+Mono&display=swap');

    /* Global typography */
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif !important;
    }

    /* Sidebar borders */
    [data-testid="stSidebar"] {
        border-right: 1px solid #1e3a5a;
    }
    
    /* Code/Mono inputs */
    input[type="password"], .stTextInput > div > div > input {
        font-family: 'JetBrains Mono', monospace !important;
        color: #c1ddf9 !important;
        background-color: #00182b !important;
        border: 1px solid #1e3a5a !important;
    }

    /* Metric/Card styling for dataframes */
    [data-testid="stDataFrame"] > div {
        background-color: #002b4d;
        border: 1px solid #1e3a5a;
        border-radius: 8px;
    }

    /* Button styling */
    .stButton > button {
        background-color: #f37324;
        color: white;
        border: none;
        border-radius: 4px;
        font-weight: 600;
        transition: all 0.3s ease;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
    }
    .stButton > button:hover {
        background-color: #d9651f;
        color: white;
        border-color: #d9651f;
    }
    
    /* Dividers */
    hr {
        border-color: #1e3a5a !important;
    }
    </style>
    """, unsafe_allow_html=True)

def apply_elegant_theme(fig):
    fig.update_layout(
        paper_bgcolor='#002b4d',
        plot_bgcolor='#002b4d',
        font=dict(color='#f0f6fd', family='Inter'),
        title_font=dict(size=16, color='#c1ddf9', family='Inter'),
        legend=dict(font=dict(color='#92c1ed')),
        xaxis=dict(gridcolor='#1e3a5a', zerolinecolor='#1e3a5a', tickfont=dict(color='#6e9fc8')),
        yaxis=dict(gridcolor='#1e3a5a', zerolinecolor='#1e3a5a', tickfont=dict(color='#6e9fc8')),
        margin=dict(l=20, r=20, t=40, b=20)
    )
    return fig

# ==========================================
# DATA INGESTION & PROCESSING
# ==========================================
def clean_currency(val):
    if pd.isna(val):
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    val = str(val).replace('$', '').replace(',', '').strip()
    if not val:
        return 0.0
    try:
        return float(val)
    except:
        return 0.0

def identify_and_parse(file):
    # Read the first few lines to identify the report type
    content = file.read().decode('utf-8')
    lines = content.split('\n')
    report_type = "Unknown"
    for i in range(5):
        if i < len(lines):
            line = lines[i].lower()
            if "profit and loss" in line:
                report_type = "PL"
                break
            elif "balance sheet" in line:
                report_type = "BS"
                break
            elif "cash flow" in line:
                report_type = "CF"
                break
    
    # Reset file pointer and parse
    file.seek(0)
    # Typically QuickBooks exports have metadata in first 4 rows
    df = pd.read_csv(file, skiprows=4)
    # The first column is usually the account name. We rename it for consistency.
    df.rename(columns={df.columns[0]: 'Account'}, inplace=True)
    df.dropna(subset=['Account'], inplace=True)
    
    # Remove 'Total' column if it exists
    if 'Total' in df.columns:
        df = df.drop(columns=['Total'])
        
    # Clean currency values
    for col in df.columns[1:]:
        df[col] = df[col].apply(clean_currency)
        
    return report_type, df

def extract_metric(df, keywords):
    for _, row in df.iterrows():
        acct = str(row['Account']).lower()
        if any(k in acct for k in keywords):
            return row[1:].astype(float)
    # Return zero series if not found
    return pd.Series(0.0, index=df.columns[1:])

# ==========================================
# MAIN APP
# ==========================================
def main():
    inject_custom_css()
    st.title("Financial Analytics & Executive Summary")
    st.markdown("Automated financial insights based on the Vernimmen Four-Stage Plan.")
    
    # Sidebar
    st.sidebar.header("Data Upload")
    uploaded_files = st.sidebar.file_uploader(
        "Upload QuickBooks CSVs (P&L, Balance Sheet, Cash Flows)", 
        type="csv", 
        accept_multiple_files=True
    )
    
    st.sidebar.header("AI Settings")
    api_key = st.sidebar.text_input("Gemini API Key", type="password")
    
    if not uploaded_files or len(uploaded_files) < 3:
        st.info("Please upload all three files (Profit & Loss, Balance Sheet, Statement of Cash Flows) to begin.")
        return
        
    # Process files
    reports = {}
    for f in uploaded_files:
        rtype, df = identify_and_parse(f)
        reports[rtype] = df
        
    if "PL" not in reports or "BS" not in reports or "CF" not in reports:
        st.error("Could not confidently identify one or more of the required reports (P&L, Balance Sheet, Cash Flow). Please check the file contents.")
        return
        
    pl_df = reports["PL"]
    bs_df = reports["BS"]
    cf_df = reports["CF"]
    
    # Get common months
    months = [col for col in pl_df.columns if col != 'Account']
    
    # --- Extract P&L Metrics ---
    sales = extract_metric(pl_df, ['total for income', 'total income'])
    cogs = extract_metric(pl_df, ['total for cost of goods sold', 'total cost of goods sold'])
    gross_profit = extract_metric(pl_df, ['gross profit'])
    expenses = extract_metric(pl_df, ['total for expenses', 'total expenses'])
    net_income = extract_metric(pl_df, ['net income'])
    
    if gross_profit.sum() == 0:
        gross_profit = sales - cogs
        
    # --- Extract BS Metrics ---
    current_assets = extract_metric(bs_df, ['total for current assets', 'total current assets'])
    inventory = extract_metric(bs_df, ['inventory asset', 'inventory'])
    total_assets = extract_metric(bs_df, ['total for assets', 'total assets'])
    current_liabilities = extract_metric(bs_df, ['total for current liabilities', 'total current liabilities'])
    
    working_capital = current_assets - current_liabilities
    capital_employed = total_assets - current_liabilities
    
    current_ratio = current_assets / current_liabilities.replace(0, np.nan)
    quick_ratio = (current_assets - inventory) / current_liabilities.replace(0, np.nan)
    
    # --- Extract CF Metrics ---
    cf_operating = extract_metric(cf_df, ['net cash provided by operating activities'])
    cf_investing = extract_metric(cf_df, ['net cash provided by investing activities'])
    cf_financing = extract_metric(cf_df, ['net cash provided by financing activities'])
    cf_net = extract_metric(cf_df, ['net cash increase for period'])
    
    # Construct combined metrics DataFrame
    metrics_df = pd.DataFrame({
        'Month': months,
        'Sales': sales.values,
        'COGS': cogs.values,
        'Gross Profit': gross_profit.values,
        'Expenses': expenses.values,
        'Net Income': net_income.values,
        'Current Assets': current_assets.values,
        'Current Liabilities': current_liabilities.values,
        'Working Capital': working_capital.values,
        'Capital Employed': capital_employed.values,
        'Current Ratio': current_ratio.values,
        'Quick Ratio': quick_ratio.values,
        'Operating CF': cf_operating.values,
        'Investing CF': cf_investing.values,
        'Financing CF': cf_financing.values,
        'Net CF': cf_net.values
    }).set_index('Month')
    
    st.subheader("Monthly Metrics Data")
    st.dataframe(metrics_df.style.format("{:,.2f}"))

    # ==========================================
    # VISUALIZATIONS
    # ==========================================
    st.divider()
    st.header("Financial Visualizations")
    
    col1, col2 = st.columns(2)
    
    # 1. Liquidity Gauges (Latest Month)
    with col1:
        latest_cr = metrics_df['Current Ratio'].iloc[-1]
        latest_qr = metrics_df['Quick Ratio'].iloc[-1]
        
        fig_gauge = go.Figure()
        fig_gauge.add_trace(go.Indicator(
            mode = "gauge+number",
            value = latest_cr,
            title = {'text': "Current Ratio (Latest)"},
            domain = {'x': [0, 0.45], 'y': [0, 1]},
            gauge = {'axis': {'range': [0, 3]},
                     'bar': {'color': COLORS['dark_blue']}}
        ))
        fig_gauge.add_trace(go.Indicator(
            mode = "gauge+number",
            value = latest_qr,
            title = {'text': "Quick Ratio (Latest)"},
            domain = {'x': [0.55, 1], 'y': [0, 1]},
            gauge = {'axis': {'range': [0, 3]},
                     'bar': {'color': COLORS['blue_1']}}
        ))
        fig_gauge.update_layout(height=300, margin=dict(l=20, r=20, t=30, b=20))
        fig_gauge = apply_elegant_theme(fig_gauge)
        st.plotly_chart(fig_gauge, use_container_width=True)

    # 2. Area Chart for MoM Sales vs Net Income
    with col2:
        fig_area = px.area(
            metrics_df, 
            y=['Sales', 'Net Income'], 
            color_discrete_sequence=[COLORS['blue_1'], COLORS['dark_blue']],
            title="Sales vs Net Income (MoM)"
        )
        fig_area = apply_elegant_theme(fig_area)
        st.plotly_chart(fig_area, use_container_width=True)
        
    col3, col4 = st.columns(2)
    
    # 3. Line Chart for MoM Common-Size Analysis
    with col3:
        cs_df = pd.DataFrame(index=metrics_df.index)
        cs_df['COGS %'] = metrics_df['COGS'] / metrics_df['Sales'].replace(0, np.nan) * 100
        cs_df['Expenses %'] = metrics_df['Expenses'] / metrics_df['Sales'].replace(0, np.nan) * 100
        cs_df['Net Income %'] = metrics_df['Net Income'] / metrics_df['Sales'].replace(0, np.nan) * 100
        
        fig_cs = px.line(
            cs_df, 
            y=['COGS %', 'Expenses %', 'Net Income %'],
            color_discrete_sequence=[COLORS['accent'], COLORS['negative'], COLORS['positive']],
            title="Common-Size Analysis (% of Sales)"
        )
        fig_cs = apply_elegant_theme(fig_cs)
        st.plotly_chart(fig_cs, use_container_width=True)
        
    # 4. Stacked Bar Chart for MoM Variance %
    with col4:
        var_df = metrics_df[['Sales', 'Expenses', 'Net Income']].pct_change() * 100
        # Replace infs and drop first NA row
        var_df = var_df.replace([np.inf, -np.inf], np.nan).dropna()
        
        fig_var = px.bar(
            var_df,
            barmode='relative',
            color_discrete_sequence=[COLORS['blue_2'], COLORS['negative'], COLORS['positive']],
            title="MoM Variance % (Sales, Expenses, Net Income)"
        )
        fig_var = apply_elegant_theme(fig_var)
        st.plotly_chart(fig_var, use_container_width=True)

    col5, col6 = st.columns(2)
    
    # 5. Waterfall Chart for Cash Flow Allocation
    with col5:
        # Sum CF across the period
        cf_totals = [
            metrics_df['Operating CF'].sum(),
            metrics_df['Investing CF'].sum(),
            metrics_df['Financing CF'].sum()
        ]
        
        fig_waterfall = go.Figure(go.Waterfall(
            name = "Cash Flow",
            orientation = "v",
            measure = ["relative", "relative", "relative", "total"],
            x = ["Operating", "Investing", "Financing", "Net Change"],
            y = cf_totals + [sum(cf_totals)],
            connector = {"line":{"color":"rgb(63, 63, 63)"}},
            decreasing = {"marker":{"color":COLORS['negative']}},
            increasing = {"marker":{"color":COLORS['positive']}},
            totals = {"marker":{"color":COLORS['dark_blue']}}
        ))
        fig_waterfall.update_layout(title="Cash Flow Allocation (Period Total)", showlegend=False)
        fig_waterfall = apply_elegant_theme(fig_waterfall)
        st.plotly_chart(fig_waterfall, use_container_width=True)
        
    # 6. Dual-Axis Chart for Capital Employed vs Working Capital
    with col6:
        fig_dual = go.Figure()
        fig_dual.add_trace(go.Bar(
            x=metrics_df.index,
            y=metrics_df['Capital Employed'],
            name='Capital Employed',
            marker_color=COLORS['blue_3']
        ))
        fig_dual.add_trace(go.Scatter(
            x=metrics_df.index,
            y=metrics_df['Working Capital'],
            name='Working Capital',
            mode='lines+markers',
            line=dict(color=COLORS['accent'], width=3),
            yaxis='y2'
        ))
        fig_dual.update_layout(
            title="Capital Employed vs Working Capital",
            yaxis=dict(title="Capital Employed"),
            yaxis2=dict(title="Working Capital", overlaying='y', side='right'),
            barmode='group'
        )
        fig_dual = apply_elegant_theme(fig_dual)
        st.plotly_chart(fig_dual, use_container_width=True)
        
    # 7. Bridge/Walk Chart for "Scissors Effect" (Price/Volume vs Cost)
    # Using Sales Growth vs Expense Growth to illustrate margin changes
    st.subheader("Scissors Effect: Margin Walk (Total Period)")
    sales_growth = metrics_df['Sales'].iloc[-1] - metrics_df['Sales'].iloc[0]
    cogs_growth = metrics_df['COGS'].iloc[-1] - metrics_df['COGS'].iloc[0]
    exp_growth = metrics_df['Expenses'].iloc[-1] - metrics_df['Expenses'].iloc[0]
    net_growth = metrics_df['Net Income'].iloc[-1] - metrics_df['Net Income'].iloc[0]
    
    fig_bridge = go.Figure(go.Waterfall(
        orientation="v",
        measure=["absolute", "relative", "relative", "total"],
        x=["Starting Net Income", "Sales Growth (Volume/Price)", "Cost Growth (COGS + Opex)", "Ending Net Income"],
        y=[metrics_df['Net Income'].iloc[0], sales_growth, -(cogs_growth + exp_growth), metrics_df['Net Income'].iloc[-1]],
        decreasing={"marker":{"color":COLORS['negative']}},
        increasing={"marker":{"color":COLORS['positive']}},
        totals={"marker":{"color":COLORS['dark_blue']}}
    ))
    fig_bridge.update_layout(title="Scissors Effect Analysis")
    fig_bridge = apply_elegant_theme(fig_bridge)
    st.plotly_chart(fig_bridge, use_container_width=True)
    
    # ==========================================
    # AI EXECUTIVE SUMMARY
    # ==========================================
    st.divider()
    st.header("AI Executive Summary")
    
    if st.button("Generate Executive Summary"):
        if not api_key:
            st.error("Please enter your Gemini API Key in the sidebar.")
        else:
            with st.spinner("Analyzing financial data & generating insights..."):
                try:
                    # Initialize Gemini
                    genai.configure(api_key=api_key)
                    # Use standard models as per instructions
                    model = genai.GenerativeModel('gemini-1.5-pro')
                    
                    # Compute key inputs for the prompt
                    sales_pct = metrics_df['Sales'].pct_change().mean() * 100
                    avg_net_margin = (metrics_df['Net Income'].sum() / metrics_df['Sales'].sum()) * 100
                    trend_breaks = var_df[var_df.abs() > 10].dropna(how='all')
                    
                    prompt = f"""
                    You are a Senior Financial Analyst presenting to firm partners.
                    Based on the following month-over-month financial metrics, write a 3-paragraph executive summary based on the Vernimmen Four-Stage Plan.
                    
                    Data Summary:
                    - Average MoM Sales Growth: {sales_pct:.2f}%
                    - Overall Net Profit Margin: {avg_net_margin:.2f}%
                    - Latest Current Ratio: {latest_cr:.2f}
                    - Total Operating Cash Flow: ${cf_totals[0]:,.2f}
                    - Total Cash Flow Net Change: ${sum(cf_totals):,.2f}
                    
                    Major Trend Breaks (>10% variance):
                    {trend_breaks.to_string()}
                    
                    Requirements:
                    - Exactly 3 paragraphs.
                    - Highlight critical trend breaks.
                    - Keep the tone professional, objective, and analytical.
                    """
                    
                    response = model.generate_content(prompt)
                    st.success("Summary Generated!")
                    st.markdown(f"""
                    <div style="background-color: #001f38; border-left: 4px solid #3b82f6; padding: 20px; border-radius: 4px; margin-top: 10px;">
                        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
                            <span style="font-size: 12px; font-weight: bold; text-transform: uppercase; letter-spacing: 1px; color: #93c5fd;">AI Executive Summary</span>
                        </div>
                        <div style="font-size: 14px; line-height: 1.6; color: #eff6ff; font-weight: 300; font-style: italic;">
                            {response.text}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                except Exception as e:
                    st.error(f"Error generating summary: {str(e)}")

if __name__ == "__main__":
    main()
