import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import re
import time
import uuid
import requests
import json
from datetime import datetime
import google.generativeai as genai
import urllib.request
import xml.etree.ElementTree as ET
import yfinance as yf
from yahooquery import Ticker
from dateutil.relativedelta import relativedelta

# Import your custom data fetchers
from data_layer.gsheets_client import fetch_portfolio_data, log_daily_networth, add_new_asset

# Safely import the new harvest function
try:
    from data_layer.gsheets_client import harvest_dividend
except ImportError:
    harvest_dividend = None

# --- PAGE SETUP ---
st.set_page_config(
    page_title="Wealth Terminal", 
    page_icon="📈", 
    layout="wide",
    initial_sidebar_state="collapsed" 
)

# --- GLASSMORPHISM CSS INJECTION ---
st.markdown("""
<style>
    [data-testid="stSidebarNav"] {display: none !important;}

    [data-testid="stMetric"] {
        background: linear-gradient(145deg, #1f2937, #111827);
        border: 1px solid #374151;
        border-radius: 12px;
        padding: 24px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2), 0 2px 4px -1px rgba(0, 0, 0, 0.1);
        transition: transform 0.2s ease, border-color 0.2s ease;
    }
    [data-testid="stMetric"]:hover {
        transform: translateY(-2px);
        border-color: #3b82f6;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.8rem !important; 
        font-weight: 800 !important;
        letter-spacing: -0.5px;
    }

    /* Hide default Streamlit dataframe headers to prefer our custom HTML tables */
    [data-testid="stDataFrame"] {
        background-color: transparent;
        border-radius: 12px;
        overflow: hidden;
    }

    /* --- NEW GLASSMORPHISM TABLE WITH SORTING ICONS --- */
    .glass-table {
        width: 100%;
        border-collapse: separate;
        border-spacing: 0;
        background: linear-gradient(145deg, rgba(31, 41, 55, 0.3), rgba(17, 24, 39, 0.5));
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border-radius: 12px;
        overflow: hidden;
        color: #f3f4f6;
        border: 1px solid rgba(55, 65, 81, 0.6);
        font-family: sans-serif;
        font-size: 0.9rem;
    }
    .glass-table thead th {
        background: rgba(17, 24, 39, 0.8);
        padding: 14px 16px;
        text-align: left;
        font-weight: 600;
        color: #9ca3af;
        border-bottom: 1px solid rgba(55, 65, 81, 0.8);
        text-transform: uppercase;
        font-size: 0.75rem;
        letter-spacing: 0.05em;
        cursor: pointer;
        position: relative;
        padding-right: 20px !important;
        transition: color 0.2s ease;
    }
    .glass-table thead th:hover {
        color: #ffffff;
    }
    .glass-table thead th::after {
        content: '↕';
        position: absolute;
        right: 6px;
        opacity: 0.3;
    }
    .glass-table tbody td {
        padding: 12px 16px;
        border-bottom: 1px solid rgba(55, 65, 81, 0.3);
    }
    .glass-table tbody tr:last-child td {
        border-bottom: none;
    }
    .glass-table tbody tr:hover {
        background: rgba(59, 130, 246, 0.15);
        transition: background 0.2s ease;
    }

    .news-link a {
        color: #60a5fa !important;
        text-decoration: none;
        font-size: 0.95rem;
        line-height: 1.6;
        transition: color 0.2s ease;
    }
    .news-link a:hover {
        color: #93c5fd !important;
        text-decoration: underline;
    }

    div.stButton > button[kind="primary"] {
        background: linear-gradient(to right, #1e3a8a, #3b82f6);
        color: white;
        border: none;
        border-radius: 8px;
        height: 55px;
        font-size: 1.2rem !important;
        font-weight: 700 !important;
        letter-spacing: 0.5px;
        box-shadow: 0 4px 15px rgba(59, 130, 246, 0.4);
        transition: all 0.3s ease;
    }
    div.stButton > button[kind="primary"]:hover {
        box-shadow: 0 6px 20px rgba(59, 130, 246, 0.6);
        transform: scale(1.02);
    }
</style>
""", unsafe_allow_html=True)

# --- GLOBAL API FETCHERS ---
@st.cache_data(ttl=1800)
def fetch_global_news():
    news_items = {"US": [], "IN": []}
    urls = {
        "US": "https://news.google.com/rss/search?q=Wall+Street+OR+US+Stock+Market+finance+when:1d&hl=en-US&gl=US&ceid=US:en",
        "IN": "https://news.google.com/rss/search?q=Nifty+50+Indian+Stock+Market+when:1d&hl=en-IN&gl=IN&ceid=IN:en"
    }
    for region, url in urls.items():
        try:
            req = urllib.request.urlopen(url)
            root = ET.parse(req).getroot()
            for item in root.findall('.//item')[:4]:
                title = item.find('title').text
                link = item.find('link').text
                clean_title = title.rsplit(' - ', 1)[0]
                news_items[region].append({"title": clean_title, "link": link})
        except Exception:
            pass
    return news_items

@st.cache_data(ttl=3600)
def fetch_usd_inr_rate():
    try:
        rate = yf.Ticker("USDINR=X").history(period="1d")["Close"].iloc[-1]
        return float(rate)
    except Exception:
        return 83.50

@st.cache_data(ttl=86400)
def fetch_benchmark(start_date, end_date, ticker="^NSEI"):
    try:
        start_str = pd.to_datetime(start_date).strftime("%Y-%m-%d")
        end_str = (pd.to_datetime(end_date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        data = yf.download(ticker, start=start_str, end=end_str, progress=False)
        if isinstance(data.columns, pd.MultiIndex):
            return data['Close'][ticker]
        return data['Close']
    except:
        return pd.Series(dtype=float)

@st.cache_data(ttl=86400)
def fetch_correlation_matrix(tickers):
    if not tickers or len(tickers) < 2: return pd.DataFrame()
    try:
        data = yf.download(tickers, period="1y", progress=False)
        if isinstance(data.columns, pd.MultiIndex):
            if 'Close' in data.columns.levels[0]:
                data = data['Close']
            elif 'Adj Close' in data.columns.levels[0]:
                data = data['Adj Close']
        return data.corr()
    except Exception:
        return pd.DataFrame()

# --- YAHOOQUERY HYBRID FETCHERS ---
@st.cache_data(ttl=604800)
def fetch_sectors(tickers, is_us=False):
    mapping = {}
    valid_tickers = []
    ticker_map = {}
    
    for t in set(tickers):
        if pd.isna(t) or str(t).strip() == "": continue
        ticker_str = str(t).strip()
        yq_ticker = ticker_str if (is_us or ticker_str.endswith(".NS") or ticker_str.endswith(".BO")) else f"{ticker_str}.NS"
        valid_tickers.append(yq_ticker)
        ticker_map[yq_ticker] = ticker_str
        
    if not valid_tickers: return mapping
    
    try:
        t = Ticker(valid_tickers, asynchronous=True)
        profiles = t.asset_profile
        
        for yq_t in valid_tickers:
            original_t = ticker_map[yq_t]
            if isinstance(profiles, dict) and yq_t in profiles and isinstance(profiles[yq_t], dict):
                mapping[original_t] = profiles[yq_t].get('sector', 'Unclassified')
            else:
                mapping[original_t] = 'Unclassified'
    except Exception:
        for original_t in ticker_map.values(): mapping[original_t] = "Unclassified"
            
    return mapping

@st.cache_data(ttl=86400)
def fetch_dividend_data(tickers, is_us=False):
    div_data = {}
    valid_tickers = []
    ticker_map = {}
    
    for t in set(tickers):
        if pd.isna(t) or str(t).strip() == "": continue
        ticker_str = str(t).strip()
        yq_ticker = ticker_str if (is_us or ticker_str.endswith(".NS") or ticker_str.endswith(".BO")) else f"{ticker_str}.NS"
        valid_tickers.append(yq_ticker)
        ticker_map[yq_ticker] = ticker_str

    if not valid_tickers: return div_data
    
    try:
        t = Ticker(valid_tickers, asynchronous=True)
        summary = t.summary_detail
        calendar = t.calendar_events
        
        for yq_t in valid_tickers:
            original_t = ticker_map[yq_t]
            div_data[original_t] = {"rate": 0.0, "ex_date": None, "recent_divs": []}
            
            if isinstance(summary, dict) and yq_t in summary and isinstance(summary[yq_t], dict):
                div_data[original_t]["rate"] = float(summary[yq_t].get("dividendRate", 0.0) or summary[yq_t].get("trailingAnnualDividendRate", 0.0) or 0.0)
                raw_ex = summary[yq_t].get("exDividendDate")
                if raw_ex:
                    try:
                        if isinstance(raw_ex, (int, float)): div_data[original_t]["ex_date"] = pd.to_datetime(raw_ex, unit='s').date()
                        else: div_data[original_t]["ex_date"] = pd.to_datetime(raw_ex).date()
                    except: pass
                
            if isinstance(calendar, dict) and yq_t in calendar and isinstance(calendar[yq_t], dict):
                ex_date_str = calendar[yq_t].get("exDividendDate")
                if ex_date_str:
                    try: div_data[original_t]["ex_date"] = pd.to_datetime(ex_date_str).date()
                    except: pass
    except Exception: pass
        
    thirty_days_ago = pd.Timestamp.now().tz_localize(None).normalize() - pd.Timedelta(days=30)
    today = pd.Timestamp.now().tz_localize(None).normalize()
    
    for yq_t in valid_tickers:
        original_t = ticker_map[yq_t]
        if original_t not in div_data: div_data[original_t] = {"rate": 0.0, "ex_date": None, "recent_divs": []}

        try:
            yf_ticker = yf.Ticker(yq_t)
            if not div_data[original_t]["ex_date"] or div_data[original_t]["rate"] == 0.0:
                info = yf_ticker.info
                if div_data[original_t]["rate"] == 0.0:
                    div_data[original_t]["rate"] = float(info.get("dividendRate") or info.get("trailingAnnualDividendRate") or 0.0)
                if not div_data[original_t]["ex_date"]:
                    ex_epoch = info.get("exDividendDate")
                    if ex_epoch is not None: div_data[original_t]["ex_date"] = pd.to_datetime(ex_epoch, unit='s').date()

            if div_data[original_t]["rate"] > 0 or div_data[original_t]["ex_date"]:
                hist_divs = yf_ticker.dividends
                if hist_divs is not None and not hist_divs.empty:
                    clean_index = pd.to_datetime(hist_divs.index).tz_localize(None)
                    recent_mask = (clean_index <= today) & (clean_index >= thirty_days_ago)
                    for d_date, d_val in hist_divs[recent_mask].items():
                        div_data[original_t]["recent_divs"].append({"date": d_date.date(), "amount": float(d_val)})
        except Exception: pass

    return div_data

# --- INTERACTIVE UI HTML ENGINE ---
def render_glass_table(df):
    if df is None or df.empty:
        st.write("No active positions found.")
        return
        
    table_id = "glass_table_" + str(uuid.uuid4()).replace("-", "")
    html = df.to_html(classes='glass-table', index=False, escape=False, table_id=table_id)
    
    js_code = f"""
    var table = document.getElementById('{table_id}');
    if (table && !table.dataset.sorted) {{
        table.dataset.sorted = 'true';
        var headers = table.querySelectorAll('th');
        headers.forEach(function(th, i) {{
            th.addEventListener('click', function() {{
                var tbody = table.querySelector('tbody');
                var rows = Array.from(tbody.querySelectorAll('tr'));
                var asc = th.dataset.asc === 'true';
                th.dataset.asc = !asc;

                rows.sort(function(a, b) {{
                    var valA = a.cells[i].innerText.trim();
                    var valB = b.cells[i].innerText.trim();

                    var numA = parseFloat(valA.replace(/[^0-9.-]+/g, ''));
                    var numB = parseFloat(valB.replace(/[^0-9.-]+/g, ''));

                    var isNumA = !isNaN(numA) && /[0-9]/.test(valA);
                    var isNumB = !isNaN(numB) && /[0-9]/.test(valB);

                    if (isNumA && isNumB) {{
                        return asc ? numA - numB : numB - numA;
                    }} else {{
                        return asc ? valA.localeCompare(valB) : valB.localeCompare(valA);
                    }}
                }});
                rows.forEach(function(row) {{ tbody.appendChild(row); }});
            }});
        }});
    }}
    """
    
    js_compressed = js_code.replace('\n', ' ').replace('\r', '')
    img_hack = f"<img src='dummy' onerror=\"{js_compressed}\" style='display:none;'>"
    st.markdown(html + img_hack, unsafe_allow_html=True)

# --- FORMATTING & COST-BASIS CONSOLIDATION ENGINES ---
def clean_currency(val):
    if isinstance(val, str):
        cleaned = re.sub(r'[^\d.-]', '', val)
        if cleaned == '-' or cleaned == '': return 0.0
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
        else: dec_str = ""
    if len(num_str) > 3:
        last_3 = num_str[-3:]
        rest = num_str[:-3]
        chunks = []
        while len(rest) > 0:
            chunks.append(rest[-2:])
            rest = rest[:-2]
        chunks.reverse()
        formatted_int = ",".join(chunks) + "," + last_3
    else: formatted_int = num_str
    res = formatted_int + dec_str
    return f"-{res}" if is_neg else res

# --- FIX: ROBUST NORMALIZATION ENGINE ---
def normalize_dataframe(df, val_col, inv_col, pnl_col):
    if df is None or df.empty: return df
    
    if inv_col not in df.columns:
        # Strict prioritization to prevent INR values from bleeding into USD fields
        if "Quantity" in df.columns and "Buy Price" in df.columns:
            q = pd.to_numeric(df["Quantity"].astype(str).apply(clean_currency), errors='coerce').fillna(0)
            bp = pd.to_numeric(df["Buy Price"].astype(str).apply(clean_currency), errors='coerce').fillna(0)
            df[inv_col] = q * bp
        elif "Invested" in df.columns:
            df[inv_col] = df["Invested"]
        else:
            df[inv_col] = 0.0

    if pnl_col not in df.columns:
        if "Profit/Loss" in df.columns: df[pnl_col] = df["Profit/Loss"]
        elif "Returns" in df.columns: df[pnl_col] = df["Returns"]
        elif val_col in df.columns and inv_col in df.columns:
            df[pnl_col] = df[val_col].apply(clean_currency) - df[inv_col].apply(clean_currency)
        else: df[pnl_col] = 0.0
            
    return df

# --- FIX: ROBUST USD WALLET CONSOLIDATION ---
def consolidate_positions(df, asset_class):
    if df is None or df.empty: return df
    name_col = "Assets" if asset_class == "Mutual Funds" else "Name"
    if name_col not in df.columns: return df
    
    df = df.copy()
    qty_col = next((c for c in df.columns if "qty" in c.lower() or "quantity" in c.lower() or "units" in c.lower()), None)
    inv_col = "Invested (USD)" if asset_class == "US Stocks" else ("Invested" if asset_class == "Mutual Funds" else "Invested (INR)")
    bp_col = next((c for c in df.columns if "buy price" in c.lower() or "avg price" in c.lower() or "price" in c.lower()), None)
    val_col = "Current Value (USD)" if asset_class == "US Stocks" else ("Value" if asset_class == "Mutual Funds" else "Current Value")
    pnl_col = "Profit/Loss (USD)" if asset_class == "US Stocks" else ("Returns" if asset_class == "Mutual Funds" else "Profit/Loss")
    
    for col in [qty_col, inv_col, val_col]:
        if col and col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).apply(clean_currency), errors='coerce').fillna(0)

    active_positions = []
    
    for asset, group in df.groupby(name_col):
        if str(asset).strip().upper() == "USD WALLET":
            # Correctly map USD logic strictly from Quantity (to prevent INR overlap)
            wallet_usd = group[qty_col].sum() if qty_col else 0.0
            
            # Identify the specific column where INR was dropped
            inr_candidates = [c for c in group.columns if ("inr" in c.lower() or c.lower() in ["invested", "invested amount"]) and "usd" not in c.lower()]
            inr_col = inr_candidates[0] if inr_candidates else None
            
            wallet_inr = 0.0
            if inr_col:
                wallet_inr = pd.to_numeric(group[inr_col].astype(str).apply(clean_currency), errors='coerce').fillna(0).sum()
            
            if abs(wallet_usd) > 0.001:
                wallet_row = group.iloc[-1].copy()
                wallet_row[inv_col] = wallet_usd
                wallet_row[val_col] = wallet_usd
                wallet_row["Invested (INR)"] = wallet_inr
                if pnl_col in wallet_row: wallet_row[pnl_col] = 0.0
                if qty_col in wallet_row: wallet_row[qty_col] = wallet_usd
                active_positions.append(wallet_row)
            continue
            
        if qty_col:
            net_qty = group[qty_col].sum()
            if net_qty <= 0.0001: continue 
                
            buys = group[group[qty_col] > 0]
            avg_buy_price = 0.0
            if not buys.empty and buys[qty_col].sum() > 0:
                avg_buy_price = buys[inv_col].sum() / buys[qty_col].sum()
                
            valid_rows = group[group[val_col] != 0]
            live_price = 0.0
            if not valid_rows.empty:
                last_valid = valid_rows.iloc[-1]
                if abs(last_valid[qty_col]) > 0:
                    live_price = abs(last_valid[val_col]) / abs(last_valid[qty_col])
                    
            cons_row = group.iloc[-1].copy()
            
            if "Ticker" in df.columns:
                valid_tickers = group["Ticker"].dropna().replace("", pd.NA).dropna()
                if not valid_tickers.empty: cons_row["Ticker"] = valid_tickers.iloc[0]
            
            change_col = next((col for col in df.columns if "1d change" in col.lower() or "1d" in col.lower()), None)
            if change_col and not valid_rows.empty:
                cons_row[change_col] = valid_rows.iloc[-1][change_col]
                
            cons_row[qty_col] = net_qty
            if bp_col: cons_row[bp_col] = avg_buy_price
            cons_row[inv_col] = net_qty * avg_buy_price
            cons_row[val_col] = net_qty * live_price
            if pnl_col in cons_row: cons_row[pnl_col] = cons_row[val_col] - cons_row[inv_col]
            active_positions.append(cons_row)
            
    if not active_positions: return pd.DataFrame(columns=df.columns)
    return pd.DataFrame(active_positions)

def send_telegram_report(invested, current_value, profit, daily_pnl, xirr):
    try:
        bot_token = st.secrets["TELEGRAM_BOT_TOKEN"]
        chat_id = st.secrets["TELEGRAM_CHAT_ID"]
        roi = (profit / invested * 100) if invested > 0 else 0
        message = f"""
🏛 *WEALTH TERMINAL BRIEFING* 🏛

💰 *Net Worth:* ₹{format_indian(current_value, 0)}
💵 *Total Invested:* ₹{format_indian(invested, 0)}

📈 *Total P&L:* ₹{format_indian(profit, 0)} ({roi:,.2f}%)
⚡ *1-Day Velocity:* ₹{format_indian(daily_pnl, 0)}
🔥 *Annualized XIRR:* {xirr:,.2f}%

_System Status: Synced & Active_ ✅
        """
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
        response = requests.post(url, json=payload)
        return response.status_code == 200
    except Exception as e:
        st.error(f"Telegram Engine Error: {e}")
        return False

if "current_page" not in st.session_state:
    st.session_state.current_page = "Overview"
if "harvested_tags" not in st.session_state: 
    st.session_state.harvested_tags = set()

def navigate_to_copilot(): st.session_state.current_page = "🤖 AI Co-Pilot"
def navigate_to_overview(): st.session_state.current_page = "Overview"

# --- GLOBAL DATA FETCHING ---
with st.spinner("Fetching live portfolio data..."):
    df_indian = fetch_portfolio_data("Indian Stocks")
    df_us = fetch_portfolio_data("US Stocks")
    df_mf = fetch_portfolio_data("Mutual Funds")
    df_gold = fetch_portfolio_data("Gold")
    df_crypto = fetch_portfolio_data("Crypto")
    df_history = fetch_portfolio_data("History")
    live_news_data = fetch_global_news()
    LIVE_USD_INR = fetch_usd_inr_rate()

    def strip_duplicates(df):
        if df is not None and not df.empty:
            df.columns = df.columns.str.strip()
            return df.loc[:, ~df.columns.duplicated()].copy()
        return df

    df_indian = strip_duplicates(df_indian)
    df_us = strip_duplicates(df_us)
    df_mf = strip_duplicates(df_mf)
    df_gold = strip_duplicates(df_gold)
    df_crypto = strip_duplicates(df_crypto)

    raw_df_indian = df_indian.copy() if df_indian is not None else pd.DataFrame()
    raw_df_us = df_us.copy() if df_us is not None else pd.DataFrame()
    raw_df_mf = df_mf.copy() if df_mf is not None else pd.DataFrame()
    raw_df_gold = df_gold.copy() if df_gold is not None else pd.DataFrame()
    raw_df_crypto = df_crypto.copy() if df_crypto is not None else pd.DataFrame()

    df_indian = normalize_dataframe(df_indian, "Current Value", "Invested (INR)", "Profit/Loss")
    df_indian = consolidate_positions(df_indian, "Indian Stocks")

    df_us = normalize_dataframe(df_us, "Current Value (USD)", "Invested (USD)", "Profit/Loss (USD)")
    if df_us is not None and not df_us.empty:
        wallet_mask = df_us["Name"].astype(str).str.strip().str.upper() == "USD WALLET"
        if wallet_mask.any():
            inv_usd_series = df_us.loc[wallet_mask, "Invested (USD)"].apply(clean_currency)
            df_us.loc[wallet_mask, "Current Value (USD)"] = inv_usd_series
            df_us.loc[wallet_mask, "Profit/Loss (USD)"] = 0.0
    df_us = consolidate_positions(df_us, "US Stocks")

    df_gold = normalize_dataframe(df_gold, "Current Value", "Invested (INR)", "Profit/Loss")
    df_gold = consolidate_positions(df_gold, "Gold")

    df_crypto = normalize_dataframe(df_crypto, "Current Value", "Invested (INR)", "Profit/Loss")
    df_crypto = consolidate_positions(df_crypto, "Crypto")
    
    if df_mf is not None and not df_mf.empty:
        df_mf.columns = df_mf.columns.str.strip()
        df_mf["Name"] = df_mf.get("Assets", pd.Series(dtype=str))
        df_mf = normalize_dataframe(df_mf, "Value", "Invested", "Returns")
        df_mf = consolidate_positions(df_mf, "Mutual Funds")

def calculate_xirr(df_hist):
    if df_hist is None or df_hist.empty or len(df_hist) < 2: return 0.0
    df_hist = df_hist.copy()
    df_hist["Date"] = pd.to_datetime(df_hist["Date"], errors='coerce')
    df_hist = df_hist.dropna(subset=["Date"])
    df_hist["Date_Only"] = df_hist["Date"].dt.normalize()
    df_hist = df_hist.drop_duplicates(subset=["Date_Only"], keep="last").sort_values(by="Date").reset_index(drop=True)
    
    inv_col = next((c for c in df_hist.columns if "invest" in c.lower()), "Total Invested")
    val_col = next((c for c in df_hist.columns if "value" in c.lower()), "Current Value")
    
    df_hist["Total Invested"] = pd.to_numeric(df_hist[inv_col].astype(str).apply(clean_currency), errors='coerce').fillna(0)
    df_hist["Current Value"] = pd.to_numeric(df_hist[val_col].astype(str).apply(clean_currency), errors='coerce').fillna(0)

    dates, cash_flows, prev_invested = [], [], 0
    for i in range(len(df_hist)):
        current_invested = df_hist["Total Invested"].iloc[i]
        diff = current_invested - prev_invested
        if abs(diff) > 1: 
            dates.append(df_hist["Date"].iloc[i])
            cash_flows.append(-diff) 
        prev_invested = current_invested

    if not dates: return 0.0
    dates.append(df_hist["Date"].iloc[-1])
    cash_flows.append(df_hist["Current Value"].iloc[-1])

    def xnpv(rate):
        if rate <= -1.0: return float('inf')
        d0 = dates[0]
        return sum([cf / (1.0 + rate)**((d - d0).days / 365.0) for cf, d in zip(cash_flows, dates)])

    rate = 0.1 
    try:
        for _ in range(100):
            val = xnpv(rate)
            if abs(val) < 0.01: return rate * 100
            deriv = (xnpv(rate + 0.0001) - val) / 0.0001
            if deriv == 0: break
            rate -= val / deriv
        return rate * 100
    except: return 0.0 

# --- BUILD MASTER SUMMARY & SECTOR HOLDINGS ---
summary_data = []
all_holdings = []

def process_dataframe(df, asset_name, is_us=False, fx_rate=1.0):
    if df is not None and not df.empty:
        df.columns = df.columns.str.strip()
        val_col = "Current Value (USD)" if is_us else ("Value" if asset_name == "Mutual Funds" else "Current Value")
        inv_col = "Invested (USD)" if is_us else ("Invested" if asset_name == "Mutual Funds" else "Invested (INR)")
        name_col = "Assets" if asset_name == "Mutual Funds" else "Name"
        ticker_col = "Ticker" if "Ticker" in df.columns else None
        
        if is_us:
            invested_series_inr = df.get("Invested (INR)", pd.Series([0]))
            current_series = df.get(val_col, pd.Series([0]))
            inv_val = invested_series_inr.apply(clean_currency).sum()
            if inv_val == 0:
                inv_val = df.get(inv_col, pd.Series([0])).apply(clean_currency).sum() * fx_rate
            curr_val = current_series.apply(clean_currency).sum() * fx_rate
        else:
            invested_series = df.get(inv_col, pd.Series([0]))
            current_series = df.get(val_col, pd.Series([0]))
            inv_val = invested_series.apply(clean_currency).sum() * fx_rate
            curr_val = current_series.apply(clean_currency).sum() * fx_rate
            
        if curr_val != 0 or inv_val != 0:
            summary_data.append({"Asset Class": asset_name, "Invested (INR)": inv_val, "Current Value": curr_val})
            
        if name_col in df.columns and val_col in df.columns:
            sector_map = {}
            if ticker_col and asset_name in ["Indian Equity", "US Equity"]:
                if "Sector" in df.columns:
                    missing_sectors = df[df["Sector"].isna() | (df["Sector"].astype(str).str.strip() == "") | (df["Sector"].astype(str).str.lower() == "nan")][ticker_col].dropna().tolist()
                else:
                    missing_sectors = df[ticker_col].dropna().tolist()
                sector_map = fetch_sectors(missing_sectors, is_us)

            for _, row in df.iterrows():
                val = clean_currency(row[val_col]) * fx_rate
                if val > 0:
                    name = str(row[name_col]).strip()
                    ticker_val = str(row[ticker_col]).strip() if ticker_col and pd.notna(row[ticker_col]) else ""
                    
                    if asset_name == "Mutual Funds": sector = "Mutual Funds"
                    elif asset_name == "Gold": sector = "Commodities"
                    elif asset_name == "Crypto": sector = "Cryptocurrency"
                    elif name.upper() == "USD WALLET": sector = "Cash & Equivalents"
                    else:
                        manual_sector = str(row.get("Sector", "")).strip()
                        if manual_sector and manual_sector.lower() not in ["nan", "none", ""]: sector = manual_sector 
                        elif ticker_col and pd.notna(row[ticker_col]): sector = sector_map.get(str(row[ticker_col]).strip(), "Unclassified") 
                        else: sector = "Unclassified" 
                        
                    all_holdings.append({"Asset": name, "Ticker": ticker_val, "Asset Class": asset_name, "Sector": sector, "Value": val})

process_dataframe(df_indian, "Indian Equity")
process_dataframe(df_us, "US Equity", is_us=True, fx_rate=LIVE_USD_INR)
process_dataframe(df_mf, "Mutual Funds") 
process_dataframe(df_gold, "Gold")
process_dataframe(df_crypto, "Crypto")

master_summary = pd.DataFrame(summary_data) if summary_data else pd.DataFrame()
df_all_holdings = pd.DataFrame(all_holdings) if all_holdings else pd.DataFrame()

# --- SIDEBAR: NAVIGATION & CONTROLS ---
with st.sidebar:
    st.radio(
        "🧭 Navigation", 
        ["Overview", "Indian Stocks", "US Stocks", "Mutual Funds", "Gold", "Crypto", "📊 Risk Analytics", "🔮 Wealth Forecaster", "🧾 Transaction Ledger", "🤖 AI Co-Pilot"],
        key="current_page",
        label_visibility="collapsed"
    )
    
    st.markdown("---")
    sandbox_mode = st.checkbox("🧪 Enable Sandbox Test Mode", value=False, help="Enable this when verifying math with dummy data rows to completely cutoff your live tracking records from throwing off charts.")
    
    st.markdown("---")
    if st.button("🔄 Force Data Sync", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
        
    st.markdown("---")
    st.header("➕ Log Transaction")
    tab_selection = st.selectbox("Asset Class", ["Indian Stocks", "US Stocks", "Mutual Funds", "Gold", "Crypto"])
    
    class_map = {"Indian Stocks": "Indian Equity", "US Stocks": "US Equity", "Mutual Funds": "Mutual Funds", "Gold": "Gold", "Crypto": "Crypto"}
    target_class = class_map.get(tab_selection, tab_selection)

    formatted_holdings = []
    holding_map = {}
    if not df_all_holdings.empty:
        target_df = df_all_holdings[(df_all_holdings["Asset Class"] == target_class) & (df_all_holdings["Asset"].str.upper() != "USD WALLET")]
        for _, row in target_df.iterrows():
            name = str(row["Asset"])
            tkr = str(row["Ticker"])
            label = f"{name} ({tkr})" if tkr and tkr.lower() != "nan" else name
            if label not in formatted_holdings:
                formatted_holdings.append(label)
                holding_map[label] = {"name": name, "ticker": tkr if tkr.lower() != "nan" else ""}
        formatted_holdings.sort()

    if tab_selection == "US Stocks":
        action_type = st.radio("Transaction Type", ["Buy Asset", "Sell Asset", "Add Cash to Wallet"], horizontal=True)
    else:
        action_type = st.radio("Transaction Type", ["Buy Asset", "Sell Asset"], horizontal=True)

    selected_asset_label = "➕ New Asset..."
    if action_type in ["Buy Asset", "Sell Asset"] and formatted_holdings:
        asset_options = ["➕ New Asset..."] + formatted_holdings if action_type == "Buy Asset" else formatted_holdings
        selected_asset_label = st.selectbox("Search Existing Holdings", options=asset_options, help="Type stock name or ticker to predictive auto-complete.")

    with st.form("add_asset_form", clear_on_submit=True):
        if action_type == "Add Cash to Wallet":
            new_usd = st.number_input("Deposit Amount (USD)", min_value=0.0, format="%f")
            new_inr = st.number_input("Total Cost (INR) - Locks FX Rate", min_value=0.0, format="%f")
            submit_label = "Fund Wallet"
            
        else:
            if action_type == "Sell Asset" and not formatted_holdings:
                st.info(f"No active positions found in {tab_selection} to sell.")
                new_name, new_ticker = "", ""
            elif selected_asset_label == "➕ New Asset...":
                new_name = st.text_input("Asset Name")
                new_ticker = st.text_input("Ticker / Formula Alias") if tab_selection != "Mutual Funds" else ""
            else:
                new_name = holding_map[selected_asset_label]["name"]
                new_ticker = holding_map[selected_asset_label]["ticker"]
                st.markdown(f"**Asset Identified:** {new_name} `({new_ticker})`" if new_ticker else f"**Asset Identified:** {new_name}")
                
            new_qty = st.number_input("Units / Quantity", min_value=0.0, format="%f")
            price_label = "Buy Price" if action_type == "Buy Asset" else "Sell Price"
            new_price = st.number_input(price_label, min_value=0.0, format="%f")
            
            wallet_checkbox = False
            if tab_selection == "US Stocks":
                if action_type == "Buy Asset":
                    wallet_checkbox = st.checkbox("Deduct from USD Wallet? (Keeps INR capital unchanged)", value=True)
                elif action_type == "Sell Asset":
                    wallet_checkbox = st.checkbox("Add proceeds to USD Wallet? (Keeps INR capital unchanged)", value=True)
                    
            submit_label = "Execute Buy" if action_type == "Buy Asset" else "Execute Sell"
            
        if st.form_submit_button(submit_label):
            with st.spinner("Syncing ledger with database..."):
                if action_type == "Add Cash to Wallet":
                    if new_usd > 0 and new_inr > 0:
                        success = add_new_asset("US Stocks", "USD Wallet", "CASH", new_usd, 1.0, new_inr)
                        if success:
                            st.success(f"Added ${new_usd:,.2f} to Wallet!")
                            time.sleep(1.5) 
                            st.cache_data.clear()
                            st.rerun()
                else:
                    if new_name and new_qty > 0 and new_price > 0:
                        db_qty = new_qty if action_type == "Buy Asset" else -new_qty
                        
                        if tab_selection == "US Stocks":
                            calc_invested = 0 if wallet_checkbox else "" 
                            success = add_new_asset(tab_selection, new_name, new_ticker, db_qty, new_price, calc_invested)
                            if success and wallet_checkbox:
                                wallet_impact = -(db_qty * new_price) 
                                add_new_asset(tab_selection, "USD Wallet", "CASH", wallet_impact, 1.0, 0)
                            if success:
                                st.success(f"Successfully executed {action_type} for {new_name}!")
                                time.sleep(1.5) 
                                st.cache_data.clear()
                                st.rerun()
                        else:
                            calc_invested = db_qty * new_price
                            success = add_new_asset(tab_selection, new_name, new_ticker, db_qty, new_price, calc_invested)
                            if success:
                                st.success(f"Successfully executed {action_type} for {new_name}!")
                                time.sleep(1.5) 
                                st.cache_data.clear()
                                st.rerun()

# --- INJECT LIVE DATA INTO HISTORY TIMELINE ONLY IF NOT IN SANDBOX MODE ---
if not master_summary.empty:
    live_invested = master_summary["Invested (INR)"].sum()
    live_current = master_summary["Current Value"].sum()
    today_date = pd.to_datetime("today").normalize()
    live_row = pd.DataFrame({"Date": [today_date], "Total Invested": [live_invested], "Current Value": [live_current]})
    
    if df_history is not None and not df_history.empty:
        df_history["Date"] = pd.to_datetime(df_history["Date"], errors='coerce')
        df_history = df_history.dropna(subset=["Date"])
        
        if not sandbox_mode:
            df_history = df_history[df_history["Date"].dt.normalize() != today_date]
            df_history = pd.concat([df_history, live_row], ignore_index=True)
    else:
        if not sandbox_mode: df_history = live_row

# ==========================================
# --- PAGE ROUTER LOGIC ---
# ==========================================

if st.session_state.current_page == "Overview":
    st.markdown("<h2 style='color: #3b82f6; font-weight: 800; letter-spacing: 1px;'>BLOOMBERG <span style='color: white;'>PORTFOLIO</span></h2>", unsafe_allow_html=True)
    st.markdown("<p style='color: #9ca3af; font-size: 0.8rem; margin-top: -15px;'>STATUS: <span style='color: #10b981;'>ACTIVE</span> • OVERVIEW</p>", unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    if not master_summary.empty:
        master_summary["Profit/Loss"] = master_summary["Current Value"] - master_summary["Invested (INR)"]
        master_summary["ROI (%)"] = (master_summary["Profit/Loss"] / master_summary["Invested (INR)"]) * 100
        
        total_invested = master_summary["Invested (INR)"].sum()
        total_current = master_summary["Current Value"].sum()
        total_profit = total_current - total_invested
        total_roi = (total_profit / total_invested * 100) if total_invested > 0 else 0
        portfolio_xirr = calculate_xirr(df_history)

        daily_pnl = 0.0
        def calc_asset_1d(df, is_us=False, fx=1.0):
            if df is None or df.empty: return 0.0
            change_col = next((col for col in df.columns if "1d change" in col.lower() or "1d" in col.lower()), None)
            val_col = "Current Value (USD)" if is_us else ("Value" if "Assets" in df.columns else "Current Value")
            if not change_col or val_col not in df.columns: return 0.0
            
            def parse_pct(val):
                v_str = str(val).strip()
                if not v_str or v_str.lower() in ['nan', 'none']: return 0.0
                c = re.sub(r'[^\d.-]', '', v_str)
                if not c or c in ['-', '.']: return 0.0
                num = float(c)
                if abs(num) > 50.0: num = num / 100.0
                return num

            temp = df.copy()
            name_col = "Assets" if "Assets" in temp.columns else "Name"
            if name_col in temp.columns: temp = temp[temp[name_col].astype(str).str.strip().str.upper() != "USD WALLET"]
            if temp.empty: return 0.0
            
            temp["Clean Change"] = temp[change_col].apply(parse_pct)
            temp["Target_CV"] = temp[val_col].apply(clean_currency)
            temp["Yesterday_Value"] = temp.apply(lambda row: row["Target_CV"] / (1 + (row["Clean Change"] / 100)) if row["Clean Change"] != -100 else row["Target_CV"], axis=1)
            return (temp["Target_CV"] - temp["Yesterday_Value"]).sum() * fx

        daily_pnl += calc_asset_1d(df_indian)
        daily_pnl += calc_asset_1d(df_us, is_us=True, fx=LIVE_USD_INR)
        daily_pnl += calc_asset_1d(df_mf)
        daily_pnl += calc_asset_1d(df_gold)
        daily_pnl += calc_asset_1d(df_crypto)

        yesterday_total = total_current - daily_pnl
        daily_pnl_percent = (daily_pnl / yesterday_total * 100) if yesterday_total > 0 else 0.0

        if not sandbox_mode: log_daily_networth(total_invested, total_current, total_profit)

        with st.container(border=False):
            col1, col2, col3, col4, col5 = st.columns(5)
            col1.metric("PORTFOLIO VALUE", f"₹{format_indian(total_current, 0)}")
            col2.metric("TOTAL INVESTED", f"₹{format_indian(total_invested, 0)}")
            col3.metric("PROFIT / LOSS", f"₹{format_indian(total_profit, 0)}", delta=f"{total_roi:,.2f}% ROI", delta_color="normal")
            col4.metric("1 DAY P&L", f"₹{format_indian(daily_pnl, 0)}", delta=f"{daily_pnl_percent:,.2f}%", delta_color="normal")
            col5.metric("XIRR (ANNUALIZED)", f"{portfolio_xirr:,.2f}%", delta="True Compounding", delta_color="normal")
        
        st.markdown("<br>", unsafe_allow_html=True)

        col_ai, col_tg = st.columns(2)
        with col_ai: st.button("🤖 LAUNCH TERMINAL AI CO-PILOT", type="primary", use_container_width=True, on_click=navigate_to_copilot)
        with col_tg:
            if st.button("📱 PUSH REPORT TO TELEGRAM", type="primary", use_container_width=True):
                with st.spinner("Transmitting to secure channel..."):
                    success = send_telegram_report(total_invested, total_current, total_profit, daily_pnl, portfolio_xirr)
                    if success: st.success("Briefing securely transmitted to Telegram!")
                    else: st.error("Transmission failed. Check your API token and Chat ID.")
        
        st.markdown("<br>", unsafe_allow_html=True)

        st.markdown("<h4 style='color: white;'>🌍 Live Macro Feed</h4>", unsafe_allow_html=True)
        news_col1, news_col2 = st.columns(2)
        with news_col1:
            with st.container(border=True):
                st.markdown("<h5 style='color: #9ca3af; font-size: 0.9rem; margin-bottom: 10px;'>🇺🇸 WALL STREET</h5>", unsafe_allow_html=True)
                for item in live_news_data.get("US", []):
                    st.markdown(f"<div class='news-link'>• <a href='{item['link']}' target='_blank'>{item['title']}</a></div>", unsafe_allow_html=True)

        with news_col2:
            with st.container(border=True):
                st.markdown("<h5 style='color: #9ca3af; font-size: 0.9rem; margin-bottom: 10px;'>🇮🇳 DALAL STREET (NIFTY 50)</h5>", unsafe_allow_html=True)
                for item in live_news_data.get("IN", []):
                    st.markdown(f"<div class='news-link'>• <a href='{item['link']}' target='_blank'>{item['title']}</a></div>", unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        col_velocity, col_allocation = st.columns([1.5, 1])
        with col_velocity:
            with st.container(border=True):
                st.markdown("<h4 style='color: white; margin-top: -5px;'>Portfolio Velocity</h4>", unsafe_allow_html=True)
                if df_history is not None and not df_history.empty:
                    clean_vel = df_history.copy()
                    clean_vel["Date"] = pd.to_datetime(clean_vel["Date"], errors='coerce')
                    clean_vel = clean_vel.dropna(subset=["Date"])
                    clean_vel["Date_Only"] = clean_vel["Date"].dt.normalize()
                    clean_vel = clean_vel.drop_duplicates(subset=["Date_Only"], keep="last").sort_values(by="Date")
                    
                    inv_col = next((c for c in clean_vel.columns if "invest" in c.lower()), "Total Invested")
                    val_col = next((c for c in clean_vel.columns if "value" in c.lower()), "Current Value")
                    clean_vel["Total Invested"] = pd.to_numeric(clean_vel[inv_col].astype(str).apply(clean_currency), errors='coerce').fillna(0)
                    clean_vel["Current Value"] = pd.to_numeric(clean_vel[val_col].astype(str).apply(clean_currency), errors='coerce').fillna(0)
                    
                    fig_velocity = px.line(clean_vel, x="Date", y=["Total Invested", "Current Value"], color_discrete_map={"Total Invested": "#6b7280", "Current Value": "#3b82f6"})
                    fig_velocity.update_traces(line_shape='spline', line=dict(width=3))
                    fig_velocity.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", margin=dict(t=50, b=0, l=0, r=0), xaxis=dict(showgrid=False, title=""), yaxis=dict(showgrid=True, gridcolor="#374151", title="", fixedrange=False), hovermode="x unified", legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, title_text=""))
                    fig_velocity.update_xaxes(rangeslider_visible=False, rangeselector=dict(buttons=list([dict(count=1, label="1D", step="day", stepmode="backward"), dict(count=7, label="1W", step="day", stepmode="backward"), dict(count=1, label="1M", step="month", stepmode="backward"), dict(count=3, label="3M", step="month", stepmode="backward"), dict(count=1, label="YTD", step="year", stepmode="todate"), dict(count=1, label="1Y", step="year", stepmode="backward"), dict(step="all", label="ALL")]), bgcolor="#1f2937", activecolor="#3b82f6", font=dict(color="#d1d5db", size=11), yanchor="bottom", y=1.02, xanchor="left", x=0))
                    st.plotly_chart(fig_velocity, use_container_width=True)
                else: st.info("Gathering velocity data...")

        with col_allocation:
            with st.container(border=True):
                st.markdown("<h4 style='color: white; margin-top: -5px;'>Asset Allocation</h4>", unsafe_allow_html=True)
                neon_colors = ["#3b82f6", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899", "#14b8a6"]
                fig_donut = px.pie(master_summary, values="Current Value", names="Asset Class", hole=0.6, color_discrete_sequence=neon_colors)
                fig_donut.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", margin=dict(t=10, b=0, l=0, r=0), legend=dict(orientation="v", yanchor="top", y=0.5, xanchor="left", x=1.1), annotations=[dict(text="100%", x=0.5, y=0.5, font_size=20, showarrow=False, font_color="white")])
                fig_donut.update_traces(textinfo='none') 
                st.plotly_chart(fig_donut, use_container_width=True)

        st.markdown("<br>", unsafe_allow_html=True)
        
        with st.container(border=True):
            st.markdown("<h4 style='color: white; margin-top: -5px;'>Relative Performance Engine (Composite Base 100)</h4>", unsafe_allow_html=True)
            st.markdown("<p style='color: #9ca3af; font-size: 0.9rem;'>Compares your portfolio against a dynamic blend of the Nifty 50 & S&P 500.</p>", unsafe_allow_html=True)
            
            if df_history is not None and len(df_history) > 1:
                df_bench = df_history.copy()
                df_bench["Date"] = pd.to_datetime(df_bench["Date"], errors='coerce')
                df_bench = df_bench.dropna(subset=["Date"])
                df_bench["Date_Only"] = df_bench["Date"].dt.normalize()
                df_bench = df_bench.drop_duplicates(subset=["Date_Only"], keep="last").sort_values(by="Date").reset_index(drop=True)
                
                if len(df_bench) > 1:
                    start_date = df_bench["Date"].min()
                    end_date = df_bench["Date"].max()
                    
                    nifty_data = fetch_benchmark(start_date, end_date, "^NSEI")
                    sp500_data = fetch_benchmark(start_date, end_date, "^GSPC")
                    
                    if not nifty_data.empty and not sp500_data.empty:
                        in_equity = master_summary.loc[master_summary['Asset Class'] == 'Indian Equity', 'Current Value'].sum()
                        us_equity = master_summary.loc[master_summary['Asset Class'] == 'US Equity', 'Current Value'].sum()
                        total_equity = in_equity + us_equity
                        
                        w_in = in_equity / total_equity if total_equity > 0 else 1.0
                        w_us = us_equity / total_equity if total_equity > 0 else 0.0

                        inv_col_hist = next((c for c in df_bench.columns if "invest" in c.lower()), "Total Invested")
                        val_col_hist = next((c for c in df_bench.columns if "value" in c.lower()), "Current Value")
                        
                        df_bench["Current Value"] = pd.to_numeric(df_bench[val_col_hist].astype(str).apply(clean_currency), errors='coerce').fillna(0)
                        df_bench["Total Invested"] = pd.to_numeric(df_bench[inv_col_hist].astype(str).apply(clean_currency), errors='coerce').fillna(0)
                        
                        df_bench["Prev_Value"] = df_bench["Current Value"].shift(1).fillna(df_bench["Current Value"])
                        df_bench["Prev_Invested"] = df_bench["Total Invested"].shift(1).fillna(df_bench["Total Invested"])
                        df_bench["Net_CF"] = df_bench["Total Invested"] - df_bench["Prev_Invested"]
                        
                        df_bench["True_Return"] = np.where(df_bench["Prev_Value"] > 0, (df_bench["Current Value"] - df_bench["Prev_Value"] - df_bench["Net_CF"]) / df_bench["Prev_Value"], 0.0)
                        if not sandbox_mode: df_bench["True_Return"] = df_bench["True_Return"].clip(-0.50, 0.50)
                        df_bench.loc[0, "True_Return"] = 0.0 
                        df_bench["Portfolio Growth"] = 100 * (1 + df_bench["True_Return"]).cumprod()
                        
                        df_nifty = nifty_data.reset_index()
                        df_nifty.columns = ["Date", "Nifty"]
                        df_nifty["Date"] = pd.to_datetime(df_nifty["Date"]).dt.normalize()
                        df_sp500 = sp500_data.reset_index()
                        df_sp500.columns = ["Date", "SP500"]
                        df_sp500["Date"] = pd.to_datetime(df_sp500["Date"]).dt.normalize()
                        
                        df_indices = pd.merge(df_nifty, df_sp500, on="Date", how="outer").sort_values("Date").ffill().bfill()
                        nifty_start = df_indices["Nifty"].iloc[0]
                        sp500_start = df_indices["SP500"].iloc[0]
                        df_indices["Nifty Base"] = (df_indices["Nifty"] / nifty_start) * 100
                        df_indices["SP500 Base"] = (df_indices["SP500"] / sp500_start) * 100
                        df_indices["Composite Benchmark"] = (df_indices["Nifty Base"] * w_in) + (df_indices["SP500 Base"] * w_us)
                        
                        merged = pd.merge(df_bench, df_indices[["Date", "Composite Benchmark"]], on="Date", how="left").ffill()
                        
                        fig_bench = px.line(merged, x="Date", y=["Portfolio Growth", "Composite Benchmark"], color_discrete_map={"Portfolio Growth": "#3b82f6", "Composite Benchmark": "#8b5cf6"})
                        fig_bench.update_traces(line_shape='spline', line=dict(width=3))
                        
                        fig_bench.update_layout(
                            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", margin=dict(t=40, b=0, l=0, r=0), 
                            xaxis=dict(showgrid=False, title=""), yaxis=dict(showgrid=True, gridcolor="#374151", title="Normalized Index (Base 100)"), 
                            hovermode="x unified", legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, title_text="")
                        )
                        
                        fig_bench.update_xaxes(
                            rangeslider_visible=False, 
                            rangeselector=dict(
                                buttons=list([
                                    dict(count=7, label="1W", step="day", stepmode="backward"), 
                                    dict(count=1, label="1M", step="month", stepmode="backward"), 
                                    dict(count=3, label="3M", step="month", stepmode="backward"), 
                                    dict(count=6, label="6M", step="month", stepmode="backward"),
                                    dict(count=1, label="YTD", step="year", stepmode="todate"), 
                                    dict(count=1, label="1Y", step="year", stepmode="backward"), 
                                    dict(step="all", label="MAX")
                                ]), 
                                bgcolor="#1f2937", activecolor="#3b82f6", font=dict(color="#d1d5db", size=11), 
                                yanchor="bottom", y=1.05, xanchor="left", x=0
                            )
                        )
                        st.markdown(f"<p style='color: #6b7280; font-size: 0.75rem; text-align: right; margin-top: -10px;'>Benchmark Weighting: {w_in*100:.1f}% Nifty 50 | {w_us*100:.1f}% S&P 500</p>", unsafe_allow_html=True)
                        st.plotly_chart(fig_bench, use_container_width=True)
                    else: st.info("Awaiting benchmark data sync from Yahoo Finance...")
                else: st.info("Gathering historical data to generate benchmark comparison...")
            else: st.info("Gathering historical data to generate benchmark comparison...")

        st.markdown("<br>", unsafe_allow_html=True)
        
        with st.container(border=True):
            st.markdown(f"<h4 style='color: white; margin-top: -5px;'>Global Sector Concentration (INR base: ₹{LIVE_USD_INR:.2f})</h4>", unsafe_allow_html=True)
            if not df_all_holdings.empty:
                glass_color_map = {
                    "Indian Equity": "rgba(59, 130, 246, 0.28)",   
                    "US Equity": "rgba(16, 185, 129, 0.28)",     
                    "Mutual Funds": "rgba(245, 158, 11, 0.28)",   
                    "Gold": "rgba(139, 92, 246, 0.28)",            
                    "Crypto": "rgba(236, 72, 153, 0.28)"            
                }
                fig_tree = px.treemap(df_all_holdings, path=["Asset Class", "Sector", "Asset"], values="Value", color="Asset Class", color_discrete_map=glass_color_map)
                fig_tree.update_traces(
                    textinfo="label+percent parent", textfont=dict(color="#f3f4f6", size=13, family="sans-serif"),
                    marker=dict(line=dict(color="#374151", width=2)), tiling=dict(pad=12), root_color="rgba(0,0,0,0)",
                    hovertemplate="<b>%{label}</b><br>Value: ₹%{value:,.0f}<br>Weight: %{percentParent:.1%}<extra></extra>"
                )
                fig_tree.update_layout(margin=dict(t=15, l=5, r=5, b=5), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", height=550)
                st.plotly_chart(fig_tree, use_container_width=True)
            else: st.info("No active holdings found to map.")

        st.markdown("<br>", unsafe_allow_html=True)

        with st.container(border=True):
            st.markdown("<h4 style='color: white; margin-top: -5px;'>Active Positions Matrix</h4>", unsafe_allow_html=True)
            render_master = master_summary.copy()
            render_master["Invested (INR)"] = render_master["Invested (INR)"].apply(lambda x: f"₹{format_indian(clean_currency(x), 0)}")
            render_master["Current Value"] = render_master["Current Value"].apply(lambda x: f"₹{format_indian(clean_currency(x), 0)}")
            render_master["Profit/Loss"] = render_master["Profit/Loss"].apply(lambda x: f"₹{format_indian(clean_currency(x), 0)}")
            render_master["ROI (%)"] = render_master["ROI (%)"].apply(lambda x: f"{clean_currency(x):,.2f}%")
            render_glass_table(render_master)

    else:
        st.warning("No portfolio data found. Please check your Google Sheets connection.")

# --- INDIVIDUAL ASSET PAGES ---
elif st.session_state.current_page in ["Indian Stocks", "US Stocks", "Mutual Funds", "Gold", "Crypto"]:
    st.markdown(f"<h2 style='color: #3b82f6; font-weight: 800; letter-spacing: 1px;'>{st.session_state.current_page.upper()} <span style='color: white;'>LEDGER</span></h2>", unsafe_allow_html=True)
    st.markdown(f"<p style='color: #9ca3af; font-size: 0.8rem; margin-top: -15px;'>STATUS: <span style='color: #10b981;'>SYNCED</span> • {st.session_state.current_page.upper()} VIEW</p>", unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)
    
    df_map = {"Indian Stocks": df_indian, "US Stocks": df_us, "Mutual Funds": df_mf, "Gold": df_gold, "Crypto": df_crypto}
    current_df = df_map.get(st.session_state.current_page)
    
    if current_df is not None and not current_df.empty:
        display_df = current_df.copy()
        
        if "Name" in display_df.columns: display_df = display_df[display_df["Name"].notna() & (display_df["Name"].astype(str).str.strip() != "")]
        elif "Assets" in display_df.columns: display_df = display_df[display_df["Assets"].notna() & (display_df["Assets"].astype(str).str.strip() != "")]
        display_df = display_df.replace(r'^\s*$', pd.NA, regex=True)

        def render_donut_chart(df, label_col, val_col):
            if label_col in df.columns and val_col in df.columns:
                chart_data = pd.DataFrame({"Label": df[label_col], "Value": df[val_col].apply(clean_currency)})
                chart_data = chart_data[chart_data["Value"] > 0]
                if not chart_data.empty:
                    with st.container(border=True):
                        st.markdown("<h4 style='color: white; margin-top: -5px;'>Internal Weightage</h4>", unsafe_allow_html=True)
                        c1, c2, c3 = st.columns([1, 2, 1])
                        with c2:
                            fig = px.pie(chart_data, names="Label", values="Value", hole=0.6, color_discrete_sequence=px.colors.qualitative.Plotly)
                            fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", margin=dict(t=10, b=10, l=0, r=0), height=350)
                            fig.update_traces(textinfo='percent', textposition='inside', hovertemplate="%{label}<br>Value: %{value}<br>Weight: %{percent}")
                            st.columns([1, 2, 1])[1].plotly_chart(fig, use_container_width=True)
        
        total_wallet_usd = 0.0
        total_wallet_inr = 0.0
        name_col_mask = "Assets" if st.session_state.current_page == "Mutual Funds" else "Name"
        wallet_mask = pd.Series([False]*len(display_df))
        
        if st.session_state.current_page == "US Stocks" and name_col_mask in display_df.columns:
            wallet_mask = display_df[name_col_mask].astype(str).str.strip().str.upper() == "USD WALLET"
            if wallet_mask.any():
                total_wallet_usd = pd.to_numeric(display_df.loc[wallet_mask, "Invested (USD)"].astype(str).apply(clean_currency), errors='coerce').fillna(0).sum()
                
                # STRICT FIX: Safely extract INR from exact column mapping
                inr_col_disp = "Invested (INR)" if "Invested (INR)" in display_df.columns else ("Invested" if "Invested" in display_df.columns else None)
                if inr_col_disp:
                    total_wallet_inr = pd.to_numeric(display_df.loc[wallet_mask, inr_col_disp].astype(str).apply(clean_currency), errors='coerce').fillna(0).sum()
                
                display_df = display_df[~wallet_mask].copy() 

        tab_daily_val = 0
        tab_daily_pct = 0
        has_daily_data = False
        
        change_col = next((col for col in display_df.columns if "1d change" in col.lower() or "1d" in col.lower()), None)
        currency_symbol = "$" if st.session_state.current_page == "US Stocks" else "₹"
        target_value_col = "Current Value (USD)" if st.session_state.current_page == "US Stocks" else ("Value" if st.session_state.current_page == "Mutual Funds" else "Current Value")
        inv_col_name = "Invested (USD)" if st.session_state.current_page == "US Stocks" else ("Invested" if st.session_state.current_page == "Mutual Funds" else "Invested (INR)")
        pnl_col_name = "Profit/Loss (USD)" if st.session_state.current_page == "US Stocks" else ("Returns" if st.session_state.current_page == "Mutual Funds" else "Profit/Loss")

        if change_col and target_value_col in display_df.columns:
            def parse_pct(val):
                v_str = str(val).strip()
                if not v_str or v_str.lower() in ['nan', 'none']: return 0.0
                c = re.sub(r'[^\d.-]', '', v_str)
                if not c or c in ['-', '.']: return 0.0
                num = float(c)
                if abs(num) > 50.0: num = num / 100.0
                return num
                
            display_df["Clean Change"] = display_df[change_col].apply(parse_pct)
            display_df["Target_CV"] = display_df[target_value_col].apply(clean_currency)
            display_df["Yesterday_Value"] = display_df.apply(lambda row: row["Target_CV"] / (1 + (row["Clean Change"] / 100)) if row["Clean Change"] != -100 else row["Target_CV"], axis=1)
            display_df["Asset_1D_PnL"] = display_df["Target_CV"] - display_df["Yesterday_Value"]
            tab_daily_val = display_df["Asset_1D_PnL"].sum()
            total_yesterday = display_df["Yesterday_Value"].sum()
            tab_daily_pct = (tab_daily_val / total_yesterday * 100) if total_yesterday > 0 else 0
            has_daily_data = True
            
        if st.session_state.current_page == "US Stocks":
            if total_wallet_usd != 0 or wallet_mask.any():
                wallet_row = pd.DataFrame([{
                    "Name": "USD Wallet", "Ticker": "CASH", "Asset Class": "US Equity", "Sector": "Cash & Equivalents",
                    "Invested (USD)": total_wallet_usd, "Invested (INR)": total_wallet_inr,
                    "Current Value (USD)": total_wallet_usd, "Profit/Loss (USD)": 0.0,
                }])
                if change_col: wallet_row[change_col] = "0%"
                qty_col = next((c for c in display_df.columns if "qty" in c.lower() or "quantity" in c.lower()), "Quantity")
                if qty_col: wallet_row[qty_col] = total_wallet_usd
                price_col = next((c for c in display_df.columns if "price" in c.lower()), "Buy Price")
                if price_col: wallet_row[price_col] = 1.0
                display_df = pd.concat([wallet_row, display_df], ignore_index=True)

            tab_invested_usd = display_df.get("Invested (USD)", pd.Series([0])).apply(clean_currency).sum()
            tab_invested_inr = display_df.get("Invested (INR)", pd.Series([0])).apply(clean_currency).sum()
            tab_current = display_df.get(target_value_col, pd.Series([0])).apply(clean_currency).sum()
            tab_profit = display_df.get(pnl_col_name, pd.Series([0])).apply(clean_currency).sum()
            tab_roi = (tab_profit / tab_invested_usd * 100) if tab_invested_usd > 0 else 0
            
            with st.container(border=False):
                col1, col2, col3, col4, col5, col6 = st.columns(6)
                col1.metric("ASSET VALUE", f"${format_indian(tab_current, 2)}")
                col2.metric("INVESTED (USD)", f"${format_indian(tab_invested_usd, 2)}")
                col3.metric("INVESTED (INR)", f"₹{format_indian(tab_invested_inr, 0)}", delta="Fundamental Capital", delta_color="off")
                col4.metric("PROFIT / LOSS", f"${format_indian(tab_profit, 2)}", delta=f"{tab_roi:,.2f}%", delta_color="normal")
                col5.metric("USD WALLET", f"${format_indian(total_wallet_usd, 2)}", delta="Buying Power", delta_color="off")
                if has_daily_data: col6.metric("1 DAY P&L", f"${format_indian(tab_daily_val, 2)}", delta=f"{tab_daily_pct:,.2f}%", delta_color="normal")
                else: col6.metric("1 DAY P&L", "Needs Setup", delta="Add '1D Change (%)' col", delta_color="off")
        
        else:
            tab_invested = display_df.get(inv_col_name, pd.Series([0])).apply(clean_currency).sum()
            tab_current = display_df.get(target_value_col, pd.Series([0])).apply(clean_currency).sum()
            tab_profit = display_df.get(pnl_col_name, pd.Series([0])).apply(clean_currency).sum()
            tab_roi = (tab_profit / tab_invested * 100) if tab_invested > 0 else 0
            total_annual_dividends = 0
            yield_on_cost = 0
            upcoming_events = []
            recent_payouts = []

            if st.session_state.current_page == "Indian Stocks" and "Ticker" in display_df.columns:
                tickers_list = display_df["Ticker"].dropna().unique().tolist()
                with st.spinner("Scanning Dividend Calendars..."):
                    dividend_cache = fetch_dividend_data(tickers_list, is_us=False)
                
                qty_col = next((c for c in display_df.columns if "qty" in c.lower() or "quantity" in c.lower() or "units" in c.lower()), None)
                if qty_col and qty_col in display_df.columns:
                    display_df["Div_Per_Share"] = display_df["Ticker"].map(lambda x: dividend_cache.get(x, {}).get("rate", 0.0)).fillna(0.0)
                    display_df["Annual_Cashflow"] = pd.to_numeric(display_df[qty_col].astype(str).apply(clean_currency), errors='coerce').fillna(0) * display_df["Div_Per_Share"]
                    total_annual_dividends = display_df["Annual_Cashflow"].sum()
                    yield_on_cost = (total_annual_dividends / tab_invested * 100) if tab_invested > 0 else 0
                    
                    today = datetime.today().date()
                    for _, row in display_df.iterrows():
                        tk = str(row["Ticker"])
                        qty = pd.to_numeric(clean_currency(row[qty_col]))
                        ex_dt = dividend_cache.get(tk, {}).get("ex_date")
                        div_sh = dividend_cache.get(tk, {}).get("rate", 0.0)
                        
                        if ex_dt and ex_dt >= today:
                            upcoming_events.append({
                                "Asset": row["Name"], "Ticker": tk, "Upcoming Ex-Date": ex_dt.strftime("%Y-%m-%d"),
                                "Est. Payout Per Share": f"₹{div_sh:.2f}", "Estimated Total Payout": f"₹{format_indian(qty * div_sh, 0)}"
                            })
                            
                        recent_divs = dividend_cache.get(tk, {}).get("recent_divs", [])
                        for rd in recent_divs:
                             div_amount = qty * rd['amount']
                             tag = f"{tk}_{rd['date'].strftime('%Y-%m-%d')}"
                             already_harvested = tag in st.session_state.harvested_tags
                             if "Harvested_Tags" in display_df.columns and tag in str(row.get("Harvested_Tags", "")): already_harvested = True
                             if not already_harvested:
                                 recent_payouts.append({
                                     "Asset": row["Name"], "Ticker": tk, "Passed Ex-Date": rd["date"].strftime("%Y-%m-%d"),
                                     "Cash Owed": div_amount, "Tag": tag
                                 })

            with st.container(border=False):
                if st.session_state.current_page == "Indian Stocks":
                    col1, col2, col3, col4, col5 = st.columns(5)
                    col1.metric("ASSET VALUE", f"{currency_symbol}{format_indian(tab_current, 0)}")
                    col2.metric("INVESTED", f"{currency_symbol}{format_indian(tab_invested, 0)}")
                    col3.metric("PROFIT / LOSS", f"{currency_symbol}{format_indian(tab_profit, 0)}", delta=f"{tab_roi:,.2f}%", delta_color="normal")
                    if has_daily_data: col4.metric("1 DAY P&L", f"{currency_symbol}{format_indian(tab_daily_val, 0)}", delta=f"{tab_daily_pct:,.2f}%", delta_color="normal")
                    else: col4.metric("1 DAY P&L", "Needs Setup", delta="Add '1D Change (%)' col", delta_color="off")
                    col5.metric("PASSIVE INCOME (TTM)", f"₹{format_indian(total_annual_dividends, 0)}", delta=f"{yield_on_cost:,.2f}% YoC", delta_color="normal")
                else:
                    col1, col2, col3, col4 = st.columns(4)
                    col1.metric("ASSET VALUE", f"{currency_symbol}{format_indian(tab_current, 0)}")
                    col2.metric("INVESTED", f"{currency_symbol}{format_indian(tab_invested, 0)}")
                    col3.metric("PROFIT / LOSS", f"{currency_symbol}{format_indian(tab_profit, 0)}", delta=f"{tab_roi:,.2f}%", delta_color="normal")
                    if has_daily_data: col4.metric("1 DAY P&L", f"{currency_symbol}{format_indian(tab_daily_val, 0)}", delta=f"{tab_daily_pct:,.2f}%", delta_color="normal")
                    else: col4.metric("1 DAY P&L", "Needs Setup", delta="Add '1D Change (%)' col", delta_color="off")
        
            st.markdown("<br>", unsafe_allow_html=True)
            
            if st.session_state.current_page == "Indian Stocks":
                if recent_payouts:
                    with st.container(border=True):
                        st.markdown("<h4 style='color: #10b981; margin-top: -5px;'>✅ Pending Dividend Harvest</h4>", unsafe_allow_html=True)
                        st.markdown("<p style='color: #9ca3af; font-size: 0.9rem;'>Click 'Harvest' to automatically add this cash to your spreadsheet.</p>", unsafe_allow_html=True)
                        for idx, rd in enumerate(recent_payouts):
                            with st.container():
                                hc1, hc2, hc3, hc4 = st.columns([3, 2, 2, 2])
                                hc1.markdown(f"<div style='padding-top: 10px; color: #f3f4f6; font-weight: 600;'>{rd['Asset']} <span style='color: #6b7280; font-size: 0.8rem;'>{rd['Ticker']}</span></div>", unsafe_allow_html=True)
                                hc2.markdown(f"<div style='padding-top: 10px; color: #9ca3af; font-size: 0.9rem;'>Ex-Date: {rd['Passed Ex-Date']}</div>", unsafe_allow_html=True)
                                hc3.markdown(f"<div style='padding-top: 10px; color: #10b981; font-weight: 700;'>₹{format_indian(rd['Cash Owed'], 0)}</div>", unsafe_allow_html=True)
                                
                                if hc4.button("🌾 Harvest", key=f"harvest_{idx}_{rd['Ticker']}"):
                                    if harvest_dividend is None: st.error("⚠️ Add the 'harvest_dividend' function to gsheets_client.py!")
                                    else:
                                        with st.spinner("Depositing to ledger..."):
                                            success = harvest_dividend("Indian Stocks", rd['Ticker'], rd['Cash Owed'], rd['Tag'])
                                            if success:
                                                st.session_state.harvested_tags.add(rd["Tag"])
                                                st.success(f"Harvested ₹{rd['Cash Owed']}!")
                                                time.sleep(1)
                                                st.rerun()
                                            else: st.error("Database update failed.")
                            st.markdown("<hr style='margin: 0px; border-color: rgba(55, 65, 81, 0.3);'>", unsafe_allow_html=True)
                    st.markdown("<br>", unsafe_allow_html=True)

                if upcoming_events:
                    with st.container(border=True):
                        st.markdown("<h4 style='color: #f59e0b; margin-top: -5px;'>📅 Upcoming Dividend Calendar</h4>", unsafe_allow_html=True)
                        st.markdown("<p style='color: #9ca3af; font-size: 0.9rem;'>Forward-looking corporate actions detected for your active positions.</p>", unsafe_allow_html=True)
                        df_cal = pd.DataFrame(upcoming_events).sort_values(by="Upcoming Ex-Date")
                        render_glass_table(df_cal)
                else:
                    with st.container(border=True):
                        st.markdown("<h4 style='color: #6b7280; margin-top: -5px;'>📅 Upcoming Dividend Calendar</h4>", unsafe_allow_html=True)
                        st.markdown("<p style='color: #9ca3af; font-size: 0.9rem; margin-bottom: 0px;'>No pending or upcoming ex-dividend dates detected for your current positions at this time.</p>", unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)
        render_donut_chart(display_df, "Assets" if st.session_state.current_page == "Mutual Funds" else "Name", target_value_col)
        st.markdown("<br>", unsafe_allow_html=True)

        with st.container(border=True):
            st.markdown("<h4 style='color: white; margin-top: -5px;'>Position Details</h4>", unsafe_allow_html=True)
            cols_to_keep = [c for c in display_df.columns if c not in ["Clean Change", "Target_CV", "Yesterday_Value", "Asset_1D_PnL", "Div_Per_Share", "Annual_Cashflow", "Asset Class", "Invested (INR)", "Sector", "Harvested_Tags"]]
            render_df = display_df[cols_to_keep].copy()
            if st.session_state.current_page == "US Stocks" and "Name" in render_df.columns:
                render_df = render_df[render_df["Name"].astype(str).str.strip().str.upper() != "USD WALLET"]
                
            for col in render_df.columns:
                if col in ["Invested (INR)", "Current Value"]: render_df[col] = render_df[col].apply(lambda x: f"₹{format_indian(clean_currency(x), 0)}")
                elif "Invested" in col or "Value" in col or "Profit" in col or "Returns" in col: render_df[col] = render_df[col].apply(lambda x: f"{currency_symbol}{format_indian(clean_currency(x), 2 if st.session_state.current_page == 'US Stocks' else 0)}")
                elif "Price" in col: render_df[col] = render_df[col].apply(lambda x: f"{currency_symbol}{format_indian(clean_currency(x), 2)}")
                elif "Quantity" in col or "Units" in col: render_df[col] = render_df[col].apply(lambda x: f"{clean_currency(x):,.4f}" if st.session_state.current_page in ["US Stocks", "Mutual Funds"] else f"{clean_currency(x):,.0f}")
                elif "%" in col or col == change_col: render_df[col] = render_df[col].apply(lambda x: f"{clean_currency(x):,.2f}%")
            render_glass_table(render_df)
    else:
        st.info(f"No active positions found for {st.session_state.current_page}.")

# --- RAW TRANSACTION LEDGER ---
elif st.session_state.current_page == "🧾 Transaction Ledger":
    st.markdown("<h2 style='color: #10b981; font-weight: 800; letter-spacing: 1px;'>TRANSACTION <span style='color: white;'>LEDGER</span></h2>", unsafe_allow_html=True)
    st.markdown("<p style='color: #9ca3af; font-size: 0.8rem; margin-top: -15px;'>STATUS: <span style='color: #10b981;'>AUDIT MODE</span> • RAW DATABASE VIEW</p>", unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)
    st.info("💡 **Audit Mode:** This page bypasses the consolidation engine. It displays the exact, raw, unconsolidated rows directly from your Google Sheet. Use this to track down typos, duplicates, or missing transaction lines.")
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Indian Stocks", "US Stocks", "Mutual Funds", "Gold", "Crypto"])
    with tab1: render_glass_table(raw_df_indian) if not raw_df_indian.empty else st.write("No raw data found.")
    with tab2: render_glass_table(raw_df_us) if not raw_df_us.empty else st.write("No raw data found.")
    with tab3: render_glass_table(raw_df_mf) if not raw_df_mf.empty else st.write("No raw data found.")
    with tab4: render_glass_table(raw_df_gold) if not raw_df_gold.empty else st.write("No raw data found.")
    with tab5: render_glass_table(raw_df_crypto) if not raw_df_crypto.empty else st.write("No raw data found.")

# --- ALPHA METRICS & RISK ENGINE ---
elif st.session_state.current_page == "📊 Risk Analytics":
    st.markdown("<h2 style='color: #8b5cf6; font-weight: 800; letter-spacing: 1px;'>QUANTITATIVE <span style='color: white;'>ANALYTICS</span></h2>", unsafe_allow_html=True)
    st.markdown("<p style='color: #9ca3af; font-size: 0.8rem; margin-top: -15px;'>STATUS: <span style='color: #10b981;'>ENGINE ONLINE</span> • RISK EVALUATION</p>", unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    if df_history is not None and not df_history.empty and len(df_history) > 5:
        df_risk = df_history.copy()
        df_risk["Date"] = pd.to_datetime(df_risk["Date"], errors='coerce')
        df_risk = df_risk.dropna(subset=["Date"])
        df_risk["Date_Only"] = df_risk["Date"].dt.normalize()
        df_risk = df_risk.drop_duplicates(subset=["Date_Only"], keep="last").sort_values(by="Date").reset_index(drop=True)
        
        inv_col_risk = next((c for c in df_risk.columns if "invest" in c.lower()), "Total Invested")
        val_col_risk = next((c for c in df_risk.columns if "value" in c.lower()), "Current Value")
        
        df_risk["Current Value"] = pd.to_numeric(df_risk[val_col_risk].astype(str).apply(clean_currency), errors='coerce').fillna(0)
        df_risk["Total Invested"] = pd.to_numeric(df_risk[inv_col_risk].astype(str).apply(clean_currency), errors='coerce').fillna(0)
        df_risk["Prev_Value"] = df_risk["Current Value"].shift(1).fillna(df_risk["Current Value"])
        df_risk["Prev_Invested"] = df_risk["Total Invested"].shift(1).fillna(df_risk["Total Invested"])
        df_risk["Net_CF"] = df_risk["Total Invested"] - df_risk["Prev_Invested"]
        df_risk["Daily Return"] = np.where(df_risk["Prev_Value"] > 0, (df_risk["Current Value"] - df_risk["Prev_Value"] - df_risk["Net_CF"]) / df_risk["Prev_Value"], 0.0)
        if not sandbox_mode: df_risk["Daily Return"] = df_risk["Daily Return"].clip(-0.50, 0.50)
        df_risk.loc[0, "Daily Return"] = 0.0
        
        daily_rf_rate = 0.07 / 252
        mean_daily_return = df_risk["Daily Return"].mean()
        std_daily_return = df_risk["Daily Return"].std()
        downside_std = df_risk[df_risk["Daily Return"] < 0]["Daily Return"].std()
        
        sharpe_ratio = np.sqrt(252) * (mean_daily_return - daily_rf_rate) / std_daily_return if std_daily_return > 0 else 0
        sortino_ratio = np.sqrt(252) * (mean_daily_return - daily_rf_rate) / downside_std if downside_std > 0 else 0
        
        df_risk["Peak Value"] = df_risk["Current Value"].cummax()
        df_risk["Drawdown"] = (df_risk["Current Value"] - df_risk["Peak Value"]) / df_risk["Peak Value"]
        max_drawdown = df_risk["Drawdown"].min() * 100
        
        with st.container(border=True):
            st.markdown("<h4 style='color: white; margin-top: -5px;'>Alpha Scorecard</h4>", unsafe_allow_html=True)
            col1, col2, col3 = st.columns(3)
            sharpe_eval = "Excellent" if sharpe_ratio >= 2.0 else ("Good" if sharpe_ratio >= 1.0 else "Sub-optimal")
            col1.metric("SHARPE RATIO", f"{sharpe_ratio:,.2f}", delta=f"Risk-Adjusted: {sharpe_eval}", delta_color="normal" if sharpe_ratio >= 1.0 else "inverse")
            sortino_eval = "Excellent" if sortino_ratio >= 2.0 else ("Good" if sortino_ratio >= 1.0 else "Sub-optimal")
            col2.metric("SORTINO RATIO", f"{sortino_ratio:,.2f}", delta=f"Downside Risk: {sortino_eval}", delta_color="normal" if sortino_ratio >= 1.5 else "inverse")
            col3.metric("MAX DRAWDOWN", f"{max_drawdown:,.2f}%", delta="Peak-to-Trough Drop", delta_color="inverse")
        
        st.markdown("<br>", unsafe_allow_html=True)
        with st.container(border=True):
            st.markdown("<h4 style='color: white; margin-top: -5px;'>Historical Drawdown Map</h4>", unsafe_allow_html=True)
            st.markdown("<p style='color: #9ca3af; font-size: 0.9rem;'>Visualizes the depth and duration of portfolio losses from all-time highs.</p>", unsafe_allow_html=True)
            fig_dd = px.area(df_risk, x="Date", y="Drawdown", color_discrete_sequence=["#ef4444"])
            fig_dd.update_traces(line=dict(width=2), fillcolor='rgba(239, 68, 68, 0.2)')
            fig_dd.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", margin=dict(t=10, b=0, l=0, r=0), xaxis=dict(showgrid=False, title=""), yaxis=dict(showgrid=True, gridcolor="#374151", title="Drawdown %", tickformat=".1%"), hovermode="x unified")
            st.plotly_chart(fig_dd, use_container_width=True)

        st.markdown("<br>", unsafe_allow_html=True)
        with st.container(border=True):
            st.markdown("<h4 style='color: white; margin-top: -5px;'>Asset Correlation Matrix (Top 12 Holdings)</h4>", unsafe_allow_html=True)
            st.markdown("<p style='color: #9ca3af; font-size: 0.9rem;'>Evaluates your heaviest stock positions over the last 12 months. Deep red means dangerous concentration; blue means structural diversification.</p>", unsafe_allow_html=True)
            if not df_all_holdings.empty:
                valid_stocks = df_all_holdings[(df_all_holdings["Ticker"] != "") & (df_all_holdings["Asset Class"].isin(["Indian Equity", "US Equity"]))]
                top_holdings = valid_stocks.nlargest(12, "Value")
                yf_tickers = [f"{row['Ticker']}.NS" if row["Asset Class"] == "Indian Equity" and not str(row["Ticker"]).endswith(".NS") and not str(row["Ticker"]).endswith(".BO") else str(row["Ticker"]) for _, row in top_holdings.iterrows()]
                
                with st.spinner("Calculating Pearson correlations..."):
                    corr_matrix = fetch_correlation_matrix(yf_tickers)
                    
                if not corr_matrix.empty:
                    clean_labels = [c.replace(".NS", "") for c in corr_matrix.columns]
                    fig_corr = px.imshow(corr_matrix, x=clean_labels, y=clean_labels, color_continuous_scale="RdBu_r", zmin=-1, zmax=1, aspect="auto")
                    fig_corr.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", margin=dict(t=20, b=20, l=20, r=20), coloraxis_colorbar=dict(title="Correlation"))
                    st.plotly_chart(fig_corr, use_container_width=True)
                else: st.info("Awaiting sufficient ticker history to calculate correlation matrix...")
            else: st.info("Log active stock positions to generate correlation heatmaps.")

    else:
        st.warning("Not enough historical data logged to calculate quantitative risk metrics. Keep tracking daily!")

# --- WEALTH FORECASTER ---
elif st.session_state.current_page == "🔮 Wealth Forecaster":
    st.markdown("<h2 style='color: #f59e0b; font-weight: 800; letter-spacing: 1px;'>MONTE CARLO <span style='color: white;'>FORECASTER</span></h2>", unsafe_allow_html=True)
    st.markdown("<p style='color: #9ca3af; font-size: 0.8rem; margin-top: -15px;'>STATUS: <span style='color: #10b981;'>ENGINE ONLINE</span> • FUTURE WEALTH PROJECTIONS</p>", unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    if not master_summary.empty:
        current_net_worth = master_summary["Current Value"].sum()
        current_xirr = calculate_xirr(df_history)
        safe_xirr = min(max(current_xirr, 8.0), 18.0) 

        with st.container(border=True):
            st.markdown("<h4 style='color: white; margin-top: -5px;'>Simulation Parameters</h4>", unsafe_allow_html=True)
            col1, col2 = st.columns(2)
            with col1: monthly_sip = st.number_input("Planned Monthly SIP (₹)", min_value=0, value=50000, step=5000)
            with col2: expected_return = st.slider("Expected Annual CAGR (%)", min_value=5.0, max_value=30.0, value=float(safe_xirr), step=0.5)
                
        st.markdown("<br>", unsafe_allow_html=True)
        months = np.arange(1, 361) 
        r_monthly = (1 + expected_return/100)**(1/12) - 1
        future_values = current_net_worth * (1 + r_monthly)**months + monthly_sip * (((1 + r_monthly)**months - 1) / r_monthly) * (1 + r_monthly)
        df_forecast = pd.DataFrame({"Year": months / 12, "Projected Net Worth": future_values})

        with st.container(border=True):
            st.markdown("<h4 style='color: white; margin-top: -5px;'>30-Year Wealth Trajectory</h4>", unsafe_allow_html=True)
            fig_forecast = px.line(df_forecast, x="Year", y="Projected Net Worth", color_discrete_sequence=["#f59e0b"])
            fig_forecast.update_traces(line_shape='spline', line=dict(width=4))
            milestones = [10000000, 50000000, 100000000] 
            colors = ["#10b981", "#3b82f6", "#8b5cf6"]
            labels = ["₹1 Crore", "₹5 Crores", "₹10 Crores"]
            for ms, c, l in zip(milestones, colors, labels):
                fig_forecast.add_hline(y=ms, line_dash="dash", line_color=c, annotation_text=l, annotation_position="bottom right", annotation_font_color=c)
            fig_forecast.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", margin=dict(t=10, b=0, l=0, r=0), xaxis=dict(showgrid=False, title="Years from Today"), yaxis=dict(showgrid=True, gridcolor="#374151", title="Net Worth (₹)"), hovermode="x unified")
            st.plotly_chart(fig_forecast, use_container_width=True)

        years_to_1cr = df_forecast[df_forecast["Projected Net Worth"] >= 10000000]["Year"].min()
        years_to_5cr = df_forecast[df_forecast["Projected Net Worth"] >= 50000000]["Year"].min()

        colA, colB = st.columns(2)
        if pd.notna(years_to_1cr): colA.metric("Time to ₹1 Crore", f"{years_to_1cr:.1f} Years", delta="Milestone 1")
        if pd.notna(years_to_5cr): colB.metric("Time to ₹5 Crores", f"{years_to_5cr:.1f} Years", delta="Milestone 2")
    else:
        st.warning("No portfolio data found. We need a baseline net worth to forecast the future.")

# --- THE AI CO-PILOT MODULE ---
elif st.session_state.current_page == "🤖 AI Co-Pilot":
    st.markdown("<h2 style='color: #3b82f6; font-weight: 800; letter-spacing: 1px;'>TERMINAL <span style='color: white;'>CO-PILOT</span></h2>", unsafe_allow_html=True)
    st.markdown("<p style='color: #9ca3af; font-size: 0.8rem; margin-top: -15px;'>STATUS: <span style='color: #10b981;'>ONLINE</span> • AUTONOMOUS WEB RESEARCHER</p>", unsafe_allow_html=True)
    
    st.button("← Return to Overview", on_click=navigate_to_overview)
    st.markdown("---")

    if "GEMINI_API_KEY" not in st.secrets:
        st.error("🚨 **API Key Missing:** Add `GEMINI_API_KEY` to your Streamlit secrets file.")
        st.stop()

    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

    tab_chat, tab_xray = st.tabs(["💬 Portfolio Chat", "🔍 Deep-Web Earnings X-Ray"])

    # --- TAB 1: STANDARD CHAT ---
    with tab_chat:
        portfolio_context = "PORTFOLIO DATA NOT AVAILABLE."
        if not master_summary.empty:
            news_string = "=== LIVE MACRO-ECONOMIC NEWS (TODAY) ===\n"
            for item in live_news_data.get("US", []): news_string += f"US: {item['title']}\n"
            for item in live_news_data.get("IN", []): news_string += f"INDIA: {item['title']}\n"

            context_parts = [news_string, "\n=== MASTER PORTFOLIO SUMMARY ===\n" + master_summary.to_csv(index=False)]
            if df_us is not None and not df_us.empty: context_parts.append("\n=== US STOCKS ===\n" + df_us[["Name", "Ticker", "Current Value (USD)"]].dropna(subset=["Name"]).to_csv(index=False))
            if df_indian is not None and not df_indian.empty: context_parts.append("\n=== INDIAN STOCKS ===\n" + df_indian[["Name", "Ticker", "Current Value"]].dropna(subset=["Name"]).to_csv(index=False))
            portfolio_context = "\n".join(context_parts)
            
        system_prompt = f"""
        You are an elite, aggressive wealth manager and quantitative analyst. Your client has provided you with access to their live portfolio terminal. 
        Identify lazy capital, flag heavy concentrations, and suggest actionable rebalancing strategies.
        Live Data:\n{portfolio_context}
        """

        try:
            available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
            best_model_name = next((m for m in available_models if 'flash' in m.lower()), available_models[0])
            model = genai.GenerativeModel(model_name=best_model_name)
        except Exception as e:
            st.error(f"Failed to fetch models. {e}")
            st.stop()

        if "chat_history" not in st.session_state:
            st.session_state.chat_history = [{"role": "user", "content": system_prompt}, {"role": "model", "content": "Acknowledged."}]
            st.session_state.chat_history.append({"role": "assistant", "content": f"Connection established via `{best_model_name}`. Where are we deploying capital next?"})

        for message in st.session_state.chat_history[2:]:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        if user_input := st.chat_input("Ask your wealth manager..."):
            with st.chat_message("user"): st.markdown(user_input)
            st.session_state.chat_history.append({"role": "user", "content": user_input})

            with st.chat_message("assistant"):
                with st.spinner("Analyzing data..."):
                    gemini_history = [{"role": "user" if msg["role"] == "user" else "model", "parts": [msg["content"]]} for msg in st.session_state.chat_history[:-1]]
                    chat_session = model.start_chat(history=gemini_history)
                    try:
                        response = chat_session.send_message(user_input)
                        st.markdown(response.text)
                        st.session_state.chat_history.append({"role": "assistant", "content": response.text})
                    except Exception as e:
                        st.error(f"Failed to connect. {e}")

    # --- TAB 2: AUTONOMOUS EARNINGS X-RAY ---
    with tab_xray:
        st.markdown("<h4 style='color: white;'>Autonomous Fundamentals Scanner</h4>", unsafe_allow_html=True)
        st.markdown("<p style='color: #9ca3af; font-size: 0.9rem;'>The AI will autonomously search the live web for the latest earnings call transcript, press releases, and investor presentations, mapping the data into a visual health profile.</p>", unsafe_allow_html=True)
        
        active_stocks = []
        if not df_all_holdings.empty:
            active_stocks = sorted(df_all_holdings[df_all_holdings["Asset"].str.upper() != "USD WALLET"]["Asset"].unique().tolist())
            
        if not active_stocks:
            st.info("Log a transaction first to populate your active portfolio.")
        else:
            target_stock = st.selectbox("Select Asset to Scan", active_stocks)
            
            if st.button("🚀 Execute Live Web Scan", type="primary"):
                with st.spinner(f"Initiating live web scrape & analysis for {target_stock}..."):
                    
                    schema = '''
                    {
                      "quarter": "Q3 2026",
                      "growth_metrics": ["Metric 1", "Metric 2"],
                      "missed_goals": ["Miss 1", "Miss 2"],
                      "red_flags": ["Flag 1", "Flag 2"],
                      "stance_change": "Detailed summary of how management's tone or strategy has shifted.",
                      "scores": {
                          "Growth Velocity": 8, 
                          "Profitability": 7, 
                          "Risk Management": 4, 
                          "Guidance Optimism": 6
                      }
                    }
                    '''
                    
                    prompt = f"""
                    Search the live web for the latest earnings call transcript, quarterly financial results, and investor presentation for the company: {target_stock}.
                    
                    Extract the following from their actual corporate commentary:
                    1. Hard Growth Metrics (Revenues, margins, unit sales).
                    2. Missed Goals / Underperformance areas.
                    3. Red Flags / Headwinds (Debt, attrition, macro pressures).
                    4. How Management's stance or strategy has changed since the last quarter.
                    5. Rate 4 categories strictly out of 10 for a radar chart: Growth Velocity, Profitability, Risk Management, Guidance Optimism.
                    
                    Return ONLY valid JSON matching this exact structure. Do not include markdown formatting. Just the raw JSON dictionary:
                    {schema}
                    """
                    
                    try:
                        api_key = st.secrets["GEMINI_API_KEY"]
                        
                        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                        scan_model_name = next((m for m in available_models if '1.5-pro-latest' in m), None) or \
                                          next((m for m in available_models if '1.5-pro' in m), None) or \
                                          next((m for m in available_models if 'flash' in m.lower()), available_models[0])
                        
                        clean_model = scan_model_name.replace("models/", "")
                        url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_model}:generateContent?key={api_key}"
                        
                        payload = {
                            "contents": [{"parts": [{"text": prompt}]}],
                            "tools": [{"googleSearch": {}}]
                        }
                        
                        rest_response = requests.post(url, json=payload, headers={'Content-Type': 'application/json'})
                        
                        if rest_response.status_code != 200:
                            st.error(f"Google API rejected the connection: {rest_response.text}")
                            st.stop()
                            
                        raw_data = rest_response.json()
                        ai_text = raw_data['candidates'][0]['content']['parts'][0]['text']
                        
                        clean_json = ai_text.strip()
                        ticks = chr(96) * 3
                        
                        if clean_json.startswith(ticks + "json"): clean_json = clean_json[7:]
                        if clean_json.startswith(ticks): clean_json = clean_json[3:]
                        if clean_json.endswith(ticks): clean_json = clean_json[:-3]
                        
                        data = json.loads(clean_json.strip())
                        
                        st.markdown(f"### 📊 Health Profile: {target_stock} ({data.get('quarter', 'Latest')})")
                        st.markdown("<br>", unsafe_allow_html=True)
                        
                        col_radar, col_stance = st.columns([1.2, 1])
                        
                        with col_radar:
                            st.markdown("<h5 style='text-align: center; color: #9ca3af;'>Fundamental Vector Map</h5>", unsafe_allow_html=True)
                            scores = data.get("scores", {})
                            categories = list(scores.keys())
                            values = list(scores.values())
                            
                            if categories and values:
                                categories.append(categories[0])
                                values.append(values[0])
                                
                                fig = go.Figure(data=go.Scatterpolar(
                                    r=values, theta=categories, fill='toself', line_color='#3b82f6',
                                    fillcolor='rgba(59, 130, 246, 0.4)', marker=dict(size=8)
                                ))
                                fig.update_layout(
                                    polar=dict(
                                        radialaxis=dict(visible=True, range=[0, 10], color="#6b7280"),
                                        angularaxis=dict(color="#d1d5db")
                                    ),
                                    showlegend=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                                    margin=dict(t=20, b=20, l=20, r=20)
                                )
                                st.plotly_chart(fig, use_container_width=True)
                                
                        with col_stance:
                            st.markdown("#### 🧭 Management Stance")
                            st.info(data.get("stance_change", "No significant shift detected."))
                            
                            st.markdown("#### 🚨 Red Flags & Headwinds")
                            red_flags = data.get("red_flags", [])
                            if red_flags and red_flags[0] != "":
                                for flag in red_flags: st.error(f"• {flag}")
                            else:
                                st.success("No major red flags detected in latest communications.")
                                
                        st.markdown("<br>", unsafe_allow_html=True)
                                
                        col_growth, col_miss = st.columns(2)
                        with col_growth:
                            with st.container(border=True):
                                st.markdown("<h4 style='color: #10b981; margin-top: -5px;'>📈 Growth Catalysts</h4>", unsafe_allow_html=True)
                                for item in data.get("growth_metrics", []): st.markdown(f"✅ {item}")
                                    
                        with col_miss:
                            with st.container(border=True):
                                st.markdown("<h4 style='color: #f59e0b; margin-top: -5px;'>⚠️ Missed Goals</h4>", unsafe_allow_html=True)
                                misses = data.get("missed_goals", [])
                                if misses and misses[0] != "":
                                    for item in misses: st.markdown(f"📉 {item}")
                                else:
                                    st.markdown("All reported targets met.")

                    except Exception as e:
                        st.error(f"Failed to execute autonomous scan. \n\nRaw Error: {e}")
