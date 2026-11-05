import streamlit as st
import plotly.express as px
import pandas as pd

def display_portfolio_charts(df: pd.DataFrame, currency: str = "$"):
    """Displays a premium dark-themed Plotly donut chart."""
    if df.empty:
        return

    st.markdown("### Asset Allocation")
    
    fig = px.pie(
        df, 
        values='Current Value', 
        names='Ticker', 
        hole=0.65, 
        template="plotly_dark",
        color_discrete_sequence=px.colors.qualitative.Pastel 
    )
    
    hover_text = f"<b>%{{label}}</b><br>Value: {currency}%{{value:,.2f}}<br>Weight: %{{percent}}<extra></extra>"
    
    fig.update_traces(
        textposition='inside', 
        textinfo='percent',
        marker=dict(line=dict(color='#0e1117', width=4)), 
        hovertemplate=hover_text
    )
    
    fig.update_layout(
        margin=dict(t=10, b=10, l=10, r=10),
        showlegend=False, 
        hoverlabel=dict(
            bgcolor="#1f2633",
            font_size=15,
            font_family="sans-serif",
            bordercolor="#ffffff"
        )
    )
    
    st.plotly_chart(fig, use_container_width=True)