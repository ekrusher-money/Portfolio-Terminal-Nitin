import gspread
import pandas as pd
import streamlit as st
import json
import pytz
from datetime import datetime

@st.cache_resource
def get_google_client():
    """Authenticates using the raw JSON string from secrets."""
    if "GOOGLE_JSON" in st.secrets:
        try:
            creds_dict = json.loads(st.secrets["GOOGLE_JSON"])
            return gspread.service_account_from_dict(creds_dict)
        except Exception as e:
            st.error(f"🚨 Failed to decode the JSON block: {e}")
            st.stop()
    else:
        st.error("🚨 Missing GOOGLE_JSON in your Streamlit secrets!")
        st.stop()

@st.cache_data(ttl=300)
def fetch_portfolio_data(tab_name: str) -> pd.DataFrame:
    """Connects to the Google Sheet and pulls the requested tab as a DataFrame."""
    gc = get_google_client()
    
    sheet_url = st.secrets.get("SHEET_URL")
    if not sheet_url:
        st.error("🚨 SHEET_URL is missing from secrets!")
        return pd.DataFrame()
        
    try:
        spreadsheet = gc.open_by_url(sheet_url)
    except Exception as e:
        st.error(f"🚨 Connection blocked or invalid URL. Error: {e}")
        return pd.DataFrame()
        
    try:
        worksheet = spreadsheet.worksheet(tab_name)
        data = worksheet.get_all_records()
        
        if not data:
            return pd.DataFrame()
            
        return pd.DataFrame(data)
        
    except gspread.exceptions.WorksheetNotFound:
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Error fetching data for {tab_name}: {e}")
        return pd.DataFrame()

def log_daily_networth(invested, current, profit):
    """Appends today's totals to the History tab in IST."""
    gc = get_google_client()
    sheet_url = st.secrets.get("SHEET_URL")
    
    if not sheet_url:
        return 
        
    try:
        spreadsheet = gc.open_by_url(sheet_url)
        history_tab = spreadsheet.worksheet("History")
        
        ist = pytz.timezone('Asia/Kolkata')
        today = datetime.now(ist).strftime("%Y-%m-%d")
        
        data = history_tab.get_all_records()
        if data and str(data[-1].get('Date', '')) == today:
            return 
            
        history_tab.append_row([today, float(invested), float(current), float(profit)])
        
    except gspread.exceptions.WorksheetNotFound:
        st.error("🚨 'History' tab not found in Google Sheet. Please create it!")
    except Exception as e:
        st.error(f"⚠️ Could not log history: {e}")

def add_new_asset(tab_name, asset_name, ticker, quantity, buy_price, invested_amount):
    """Appends a newly purchased asset directly to the specified Google Sheet tab."""
    gc = get_google_client()
    sheet_url = st.secrets.get("SHEET_URL")
    
    if not sheet_url:
        return False
        
    try:
        spreadsheet = gc.open_by_url(sheet_url)
        worksheet = spreadsheet.worksheet(tab_name)
        
        # If Invested Amount is blank (like for US Stocks), only send the first 4 columns!
        if invested_amount == "":
            new_row = [asset_name, ticker, float(quantity), float(buy_price)]
        else:
            new_row = [asset_name, ticker, float(quantity), float(buy_price), float(invested_amount)]
            
        worksheet.append_row(new_row)
        
        return True
    except Exception as e:
        st.error(f"⚠️ Could not add asset: {e}")
        return False

import re
import streamlit as st

import re
import streamlit as st

def harvest_dividend(tab_name, ticker, amount_to_add, tag=None):
    """Finds the specific stock row, adds cash to Dividend, and logs the Harvest Tag."""
    gc = get_google_client()
    sheet_url = st.secrets.get("SHEET_URL")
    
    if not sheet_url:
        st.error("⚠️ Missing SHEET_URL in secrets.")
        return False
        
    try:
        # 1. Connect to the spreadsheet and specific tab
        spreadsheet = gc.open_by_url(sheet_url)
        worksheet = spreadsheet.worksheet(tab_name)
        
        # 2. Get headers to find columns
        header = worksheet.row_values(1)
        
        if "Ticker" not in header or "Dividend" not in header:
            st.error(f"⚠️ Missing 'Ticker' or 'Dividend' column in {tab_name} row 1.")
            return False
            
        ticker_col_idx = header.index("Ticker") + 1
        div_col_idx = header.index("Dividend") + 1
        
        # Check if the user created the permanent memory column
        tag_col_idx = None
        if "Harvested_Tags" in header:
            tag_col_idx = header.index("Harvested_Tags") + 1
            
        # 3. Pull ONLY the Ticker column to find the exact row
        all_tickers = worksheet.col_values(ticker_col_idx)
        target_ticker = str(ticker).strip()
        
        row_number = None
        for idx, val in enumerate(all_tickers):
            if str(val).strip() == target_ticker:
                row_number = idx + 1
                break
                
        if not row_number:
            st.error(f"⚠️ Could not locate ticker '{target_ticker}' in the sheet.")
            return False
            
        # 4. Fetch and update the Dividend amount securely
        current_div_val = str(worksheet.cell(row_number, div_col_idx).value)
        clean_div_str = re.sub(r'[^\d.-]', '', current_div_val)
        
        if clean_div_str == "" or clean_div_str == "None" or clean_div_str == "-":
            clean_div_str = "0"
            
        new_total = float(clean_div_str) + float(amount_to_add)
        worksheet.update_cell(row_number, div_col_idx, new_total)
        
        # 5. Log the Harvest Tag permanently (so it never shows up again)
        if tag_col_idx and tag:
            current_tags = str(worksheet.cell(row_number, tag_col_idx).value)
            if current_tags == "None" or current_tags == "":
                new_tags = tag
            else:
                new_tags = current_tags + "," + tag
            worksheet.update_cell(row_number, tag_col_idx, new_tags)
            
        return True
        
    except Exception as e:
        st.error(f"⚠️ CRITICAL HARVEST ERROR: {e}")
        return False
