import pandas as pd
import os
import glob
from datetime import datetime

def clean_csv_files(directory):
    # Find all CSV files in the directory
    csv_files = glob.glob(os.path.join(directory, "*.csv"))
    
    print(f"Found {len(csv_files)} CSV files to process.")
    
    for filepath in csv_files:
        try:
            # Skip the tracking/history files if they exist and aren't product data
            if "tcg_price_history.csv" in filepath or "pokemon_card_prices.csv" in filepath:
                continue
                
            print(f"Processing: {os.path.basename(filepath)}")
            
            # Read the CSV
            df = pd.read_csv(filepath)
            
            # Check if 'Date' column exists
            if 'Date' not in df.columns:
                print(f"  Skipping: No 'Date' column found.")
                continue
                
            # Convert Date to datetime
            df['Date'] = pd.to_datetime(df['Date'])
            
            # Remove duplicates just in case
            df = df.drop_duplicates(subset=['Date'])
            
            # Set Date as index
            df = df.set_index('Date')
            
            # Sort by date
            df = df.sort_index()
            
            if df.empty:
                print("  Skipping: Empty dataframe.")
                continue

            # Create a complete date range
            full_range = pd.date_range(start=df.index.min(), end=df.index.max(), freq='D')
            
            # Reindex to fill missing dates
            df_filled = df.reindex(full_range)
            
            # Forward fill the data (propagate last valid observation forward)
            # We use ffill() for prices and quantities because they likely stayed the same
            cols_to_ffill = [
                'Market Price', 'Most Recent Sale', 'Listed Median', 
                'Current Quantity', 'Current Sellers', 'Total Sold', 
                'Current TCGplayer Listed Quantity'
            ]
            
            # Only ffill columns that actually exist
            existing_ffill_cols = [c for c in cols_to_ffill if c in df_filled.columns]
            df_filled[existing_ffill_cols] = df_filled[existing_ffill_cols].ffill()
            
            # Fill change columns with 0 for the filled days
            # (Since we just copied the previous day's data, there was 0 change)
            cols_to_zero = ['Price Change', 'Quantity Change', 'Daily Sales']
            existing_zero_cols = [c for c in cols_to_zero if c in df_filled.columns]
            
            # We only want to zero out the rows that were *added* (where they were NaN before ffill)
            # But since we already ffilled the main data, we can just recalculate changes to be safe and accurate
            
            # Option 1: Recalculate changes entirely (Safest for consistency)
            # Convert currency strings to numbers for calculation if needed, but they seem to be strings in the CSV
            # Let's try to respect the original format.
            
            # Actually, simply filling NaNs in change columns with 0 is the most robust 
            # way to handle the "gap days" without risking parsing errors on currency strings.
            df_filled[existing_zero_cols] = df_filled[existing_zero_cols].fillna(0)
            
            # Reset index to make Date a column again
            df_filled = df_filled.reset_index()
            df_filled = df_filled.rename(columns={'index': 'Date'})
            
            # Format Date back to string YYYY-MM-DD
            df_filled['Date'] = df_filled['Date'].dt.strftime('%Y-%m-%d')
            
            # Save back to CSV
            df_filled.to_csv(filepath, index=False)
            print("  ✅ Cleaned and saved.")
            
        except Exception as e:
            print(f"  ❌ Error processing {filepath}: {e}")

if __name__ == "__main__":
    # Use the current directory where the script is located
    target_dir = os.path.dirname(os.path.abspath(__file__))
    clean_csv_files(target_dir)
