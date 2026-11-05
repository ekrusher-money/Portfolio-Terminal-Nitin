import os
from dotenv import load_dotenv

# This tells Python to read the hidden .env file we just made
load_dotenv()

# --- GOOGLE SHEETS CONFIGURATION ---
# It grabs the secret ID from your .env file
SHEET_ID = os.getenv("SPREADSHEET_ID")

# These names must exactly match the tab names in your Google Sheet!
TABS = {
    "INDIAN_STOCKS": "Indian Stocks",
    "US_STOCKS": "US Stocks",
    "MUTUAL_FUNDS": "Mutual Funds",
    "GOLD": "Gold",
    "CRYPTO": "Crypto"
}

# --- UI SETTINGS ---
CURRENCY_SYMBOLS = {
    "INR": "₹",
    "USD": "$"
}