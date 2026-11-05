import streamlit as st
import sys
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from config.settings import TABS
from data_layer.gsheets_client import fetch_portfolio_data
from data_layer.yfinance_client import fetch_live_prices
from processing.calculations import calculate_portfolio_metrics
from components.metrics import display_kpi_cards
from components.charts import display_portfolio_charts

st.set_page_config(page_title="Gold", page_icon="🪙", layout="wide")
st.title("🪙 Gold Portfolio")

gold_holdings = fetch_portfolio_data(TABS.get("GOLD", "Gold"))

if not gold_holdings.empty:
    tickers = gold_holdings['Ticker'].tolist()
    live_prices = fetch_live_prices(tickers)
    final_portfolio = calculate_portfolio_metrics(gold_holdings, live_prices)
    
    display_kpi_cards(final_portfolio, currency="₹")
    st.divider() 
    
    col_chart, col_table = st.columns([1, 2])
    with col_chart:
        display_portfolio_charts(final_portfolio, currency="₹")
    with col_table:
        st.markdown("### Live Holdings")
        st.dataframe(final_portfolio, use_container_width=True, hide_index=True)
else:
    st.warning("No data found in the Gold tab.")