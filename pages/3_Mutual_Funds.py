import streamlit as st
import pandas as pd
import plotly.express as px
import re

# Import your custom data fetcher
from data_layer.gsheets_client import fetch_portfolio_data

# --- PAGE SETUP ---
st.set_page_config(page_title="Mutual Funds", page_icon="🏦", layout="wide")

# --- CUSTOM CSS ---
st.markdown("""
<style>
    [data-testid="stMetric"] {
        background-color: #1f2937;
        border: 1px solid #374151;
        border-radius: 10px;
        padding: 20px;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.5rem !important; 
        font-weight: 700 !important;
    }
</style>
""", unsafe_allow_html=True)

# --- HELPERS ---
def clean_currency(val):
    if isinstance(val, str):
        cleaned = re.sub(r'[^\d.-]', '', val)
        try: return float(cleaned)
        except ValueError: return 0.0
    return float(val) if pd.notnull(val) else 0.0

def format_indian(number, decimals=0):
    if pd.isna(number): return "0"
    is_neg = number < 0
    number = abs(number)
    if decimals == 0:
        num_str = str(int(round(number)))
        dec_str = ""
    else:
        num_str = f"{number:.{decimals}f}"
        if "." in num_str:
            num_str, dec_str = num_str.split('.')
            dec_str = "." + dec_str
        else:
            dec_str = ""
    if len(num_str) > 3:
        last_3 = num_str[-3:]
        rest = num_str[:-3]
        chunks = []
        while len(rest) > 0:
            chunks.append(rest[-2:])
            rest = rest[:-2]
        chunks.reverse()
        formatted_int = ",".join(chunks) + "," + last_3
    else:
        formatted_int = num_str
    res = formatted_int + dec_str
    return f"-{res}" if is_neg else res

# --- MAIN APP ---
st.markdown("<h2 style='color: #3b82f6; font-weight: 800; letter-spacing: 1px;'>MUTUAL FUNDS <span style='color: white;'>LEDGER</span></h2>", unsafe_allow_html=True)
st.markdown("<br>", unsafe_allow_html=True)

with st.spinner("Syncing Mutual Fund Data..."):
    df_mf = fetch_portfolio_data("Mutual Funds")

if df_mf is not None and not df_mf.empty:
    display_df = df_mf.copy()
    display_df.columns = display_df.columns.str.strip()
    
    # 1. Ghost Row & PyArrow Sanitizer
    if "Assets" in display_df.columns:
        display_df = display_df[display_df["Assets"].notna() & (display_df["Assets"].astype(str).str.strip() != "")]
    display_df = display_df.replace(r'^\s*$', pd.NA, regex=True)
    
    # 2. Extract Data
    if all(col in display_df.columns for col in ["Invested", "Value", "Returns"]):
        tab_invested = display_df["Invested"].apply(clean_currency).sum()
        tab_current = display_df["Value"].apply(clean_currency).sum()
        tab_profit = display_df["Returns"].apply(clean_currency).sum()
        tab_roi = (tab_profit / tab_invested * 100) if tab_invested > 0 else 0
        
        # 3. Render Metrics
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("ASSET VALUE", f"₹{format_indian(tab_current, 0)}")
        col2.metric("INVESTED", f"₹{format_indian(tab_invested, 0)}")
        profit_color = "normal" if tab_profit >= 0 else "inverse"
        col3.metric("PROFIT / LOSS", f"₹{format_indian(tab_profit, 0)}", delta=f"{tab_roi:,.2f}%", delta_color=profit_color)
        col4.metric("ASSET ALPHA", f"{tab_roi:,.2f}%", delta="Sheet Sync")
        
        # 4. Render Internal Weightage Chart
        st.markdown("<br><h4 style='color: white;'>Internal Weightage</h4>", unsafe_allow_html=True)
        chart_data = pd.DataFrame({"Label": display_df["Assets"], "Value": display_df["Value"].apply(clean_currency)})
        chart_data = chart_data[chart_data["Value"] > 0]
        
        if not chart_data.empty:
            c1, c2, c3 = st.columns([1, 2, 1])
            with c2:
                fig = px.pie(chart_data, names="Label", values="Value", hole=0.6, color_discrete_sequence=px.colors.qualitative.Plotly)
                fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", margin=dict(t=10, b=10, l=0, r=0), height=350)
                fig.update_traces(textinfo='percent', textposition='inside')
                st.plotly_chart(fig, width="stretch")
        
        # 5. Render Clean Dataframe
        st.markdown("<br><h4 style='color: white;'>Position Details</h4>", unsafe_allow_html=True)
        cols_to_keep = ["Assets", "Invested", "Units", "Current Price", "Value", "Returns", "PnL%"]
        
        st.dataframe(display_df[cols_to_keep].style.format({
            "Invested": lambda x: f"₹{format_indian(clean_currency(x), 0)}",
            "Units": lambda x: f"{clean_currency(x):,.4f}",
            "Current Price": lambda x: f"₹{format_indian(clean_currency(x), 2)}",
            "Value": lambda x: f"₹{format_indian(clean_currency(x), 2)}",
            "Returns": lambda x: f"₹{format_indian(clean_currency(x), 0)}",
            "PnL%": lambda x: f"{clean_currency(x):,.2f}%"
        }), hide_index=True, width="stretch")
else:
    st.info("No active mutual funds found or sheet is empty.")
