import streamlit as st
import pandas as pd

def inject_custom_css():
    """Injects custom CSS to create Squircles, Shadows, and Hover effects."""
    st.markdown("""
    <style>
    div[data-testid="stMetric"] {
        background-color: #1f2633;
        border-radius: 20px;
        padding: 20px;
        box-shadow: 0 10px 20px rgba(0,0,0,0.2), 0 6px 6px rgba(0,0,0,0.1);
        transition: transform 0.2s ease-in-out, box-shadow 0.2s ease-in-out;
    }
    div[data-testid="stMetric"]:hover {
        transform: translateY(-5px);
        box-shadow: 0 15px 25px rgba(0,0,0,0.4), 0 10px 10px rgba(0,0,0,0.2);
    }
    </style>
    """, unsafe_allow_html=True)

# Notice the 'currency' variable is explicitly defined right here!
def display_kpi_cards(df: pd.DataFrame, currency: str = "$"):
    """Calculates overall portfolio totals and displays them as premium metric cards."""
    if df.empty:
        return

    inject_custom_css()

    total_investment = df['Total Investment'].sum()
    current_value = df['Current Value'].sum()
    total_pl = df['Total P&L'].sum()
    
    if total_investment > 0:
        pl_percentage = (total_pl / total_investment) * 100
    else:
        pl_percentage = 0.0

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric(label="Total Invested", value=f"{currency}{total_investment:,.2f}")
        
    with col2:
        st.metric(
            label="Current Portfolio Value", 
            value=f"{currency}{current_value:,.2f}", 
            delta=f"{currency}{total_pl:,.2f} ({pl_percentage:.2f}%)"
        )
        
    with col3:
        best_stock = df.loc[df['P&L %'].idxmax()]
        st.metric(
            label="🏆 Top Performer", 
            value=best_stock['Ticker'], 
            delta=f"{best_stock['P&L %']:.2f}%"
        )