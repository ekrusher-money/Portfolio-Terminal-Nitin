import pandas as pd

def calculate_portfolio_metrics(holdings_df: pd.DataFrame, live_prices: dict) -> pd.DataFrame:
    """Merges holdings with live prices and calculates P&L + Dividends."""
    if holdings_df.empty:
        return pd.DataFrame()
        
    df = holdings_df.copy()
    
    try:
        df['Current Price'] = df['Ticker'].map(live_prices)
        df['Current Price'] = df['Current Price'].fillna(df['Buy Price']) 
        
        # Base Math
        df['Total Investment'] = df['Quantity'] * df['Buy Price']
        df['Current Value'] = df['Quantity'] * df['Current Price']
        
        # 1. Standard P&L (Capital Gains only)
        df['Total P&L'] = df['Current Value'] - df['Total Investment']
        
        # 2. DIVIDEND LOGIC (Safety Net Included)
        if 'Dividend' in df.columns:
            # Convert to numbers, turn any blanks into 0.0
            df['Dividend'] = pd.to_numeric(df['Dividend'], errors='coerce').fillna(0.0)
        else:
            df['Dividend'] = 0.0
            
        # 3. Total Return (The True Metric)
        df['Total Return'] = df['Total P&L'] + df['Dividend']
        
        # Calculate percentages
        df['P&L %'] = ((df['Total P&L'] / df['Total Investment']) * 100).round(2)
        df['Return %'] = ((df['Total Return'] / df['Total Investment']) * 100).round(2)
        
        return df
        
    except KeyError as e:
        raise KeyError(f"Your Google Sheet is missing a required column: {e}")