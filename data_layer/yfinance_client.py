import yfinance as yf
import pandas as pd
import streamlit as st

@st.cache_data(ttl=300)
def get_usd_inr_rate() -> float:
    """Fetches the live USD to INR exchange rate."""
    try:
        ticker = yf.Ticker("USDINR=X")
        data = ticker.history(period="1d")
        if not data.empty:
            return float(data['Close'].iloc[-1])
    except Exception as e:
        print(f"Warning: Could not fetch USD/INR rate. Error: {e}")
    return 83.50  

@st.cache_data(ttl=300)
def get_synthetic_gold_price() -> float:
    """Calculates SGB price using highly liquid Indian Gold ETFs (GoldBees) as a proxy."""
    try:
        # GOLDBEES.NS represents 0.01 grams of physical gold in India
        etf = yf.Ticker("GOLDBEES.NS")
        data = etf.history(period="5d")
        
        if not data.empty:
            etf_price = float(data['Close'].iloc[-1])
            
            # Math: 1 gram of physical Indian gold = ETF Price * 100
            indian_physical_gold_price = etf_price * 100
            
            # SGBs typically trade at a ~3% discount to physical gold on the NSE
            sgb_fair_value = indian_physical_gold_price * 1
            
            return sgb_fair_value
            
    except Exception as e:
        print(f"Warning: Could not compute synthetic gold via GoldBees. Error: {e}")
        
    return 7400.00 # Structural fallback

@st.cache_data(ttl=60) 
def fetch_live_prices(tickers: list) -> dict:
    if not tickers:
        return {}

    prices = {}
    
    # WARM UP THE ENGINE: If the user owns any SGBs, calculate our synthetic price once
    sgb_synthetic_price = None
    if any(ticker.startswith('SGB') for ticker in tickers):
        sgb_synthetic_price = get_synthetic_gold_price()
    
    for ticker in tickers:
        # THE INTERCEPTOR: If it's an SGB, bypass Yahoo's broken stock API entirely
        if ticker.startswith('SGB'):
            prices[ticker] = sgb_synthetic_price
            continue
            
        # Standard lookup for normal stocks and ETFs
        try:
            stock = yf.Ticker(ticker)
            historical_data = stock.history(period="5d")
            
            if not historical_data.empty:
                latest_price = float(historical_data['Close'].iloc[-1])
                prices[ticker] = latest_price
                
        except Exception as e:
            print(f"Warning: Could not fetch {ticker}. Error: {e}")
            
    return prices