import streamlit as st
import sys
import os

# GPS Path Fix
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from config.settings import TABS
from data_layer.gsheets_client import fetch_portfolio_data
from data_layer.yfinance_client import fetch_live_prices
from processing.calculations import calculate_portfolio_metrics

# --- NEW IMPORTS: Bring in our UI widgets ---
from components.metrics import display_kpi_cards
from components.charts import display_portfolio_charts

st.set_page_config(page_title="US Stocks", page_icon="🇺🇸", layout="wide")
st.title("🇺🇸 US Equity Portfolio")

# 1. Fetch and Calculate Data
us_holdings = fetch_portfolio_data(TABS["US_STOCKS"])

if not us_holdings.empty:
    tickers = us_holdings['Ticker'].tolist()
    live_prices = fetch_live_prices(tickers)
    final_portfolio = calculate_portfolio_metrics(us_holdings, live_prices)
    
    # --- 2. RENDER THE UI ---
    
    # Step A: Show the big numbers at the very top
    display_kpi_cards(final_portfolio)
    st.divider() # Draws a clean horizontal line
    
    # Step B: Split the screen into two columns for the chart and table
    col_chart, col_table = st.columns([1, 2]) # Table gets twice as much space as the chart
    
    with col_chart:
        display_portfolio_charts(final_portfolio)
        
    with col_table:
        st.markdown("### Live Holdings")
        st.dataframe(
            final_portfolio,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Buy Price": st.column_config.NumberColumn(format="$%.2f"),
                "Current Price": st.column_config.NumberColumn(format="$%.2f"),
                "Total Investment": st.column_config.NumberColumn(format="$%.2f"),
                "Current Value": st.column_config.NumberColumn(format="$%.2f"),
                "Total P&L": st.column_config.NumberColumn(format="$%.2f"),
                "P&L %": st.column_config.NumberColumn(format="%.2f%%"),
            }
        )
else:
    st.warning("No data found in the US Stocks tab.")