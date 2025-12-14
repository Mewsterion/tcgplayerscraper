import os
import pandas as pd
from rich.console import Console
from rich.table import Table
from rich import box
import glob

console = Console()

def clean_currency(x):
    if isinstance(x, str):
        return float(x.replace('$', '').replace(',', ''))
    return x

def analyze_file(filepath):
    try:
        df = pd.read_csv(filepath)
        
        # Check if required columns exist
        required_cols = ['Date', 'Market Price']
        if not all(col in df.columns for col in required_cols):
            return None

        # Clean data
        df['Date'] = pd.to_datetime(df['Date'])
        df['Market Price'] = df['Market Price'].apply(clean_currency)
        df = df.sort_values('Date')
        
        if len(df) < 2:
            return None

        current_price = df['Market Price'].iloc[-1]
        
        # Calculate changes
        # 7 Day
        day7_idx = df.index[df['Date'] >= (df['Date'].iloc[-1] - pd.Timedelta(days=7))]
        if len(day7_idx) > 0:
            price_7d_ago = df['Market Price'].loc[day7_idx[0]]
            change_7d = ((current_price - price_7d_ago) / price_7d_ago) * 100
        else:
            change_7d = 0.0

        # 30 Day
        day30_idx = df.index[df['Date'] >= (df['Date'].iloc[-1] - pd.Timedelta(days=30))]
        if len(day30_idx) > 0:
            price_30d_ago = df['Market Price'].loc[day30_idx[0]]
            change_30d = ((current_price - price_30d_ago) / price_30d_ago) * 100
        else:
            change_30d = 0.0

        # Recommendation Logic
        recommendation = "HOLD"
        color = "yellow"
        
        if change_7d < -5 and change_30d > 0:
            recommendation = "BUY (Dip)"
            color = "green"
        elif change_30d > 10 and change_7d > 0:
            recommendation = "BUY (Momentum)"
            color = "green"
        elif change_7d > 15:
            recommendation = "SELL (Spike)"
            color = "red"
        elif change_30d < -10:
            recommendation = "SELL (Downtrend)"
            color = "red"

        product_name = os.path.basename(filepath).replace('.csv', '')
        # Truncate long names
        if len(product_name) > 50:
            product_name = product_name[:47] + "..."

        return {
            "Product": product_name,
            "Price": current_price,
            "7d %": change_7d,
            "30d %": change_30d,
            "Rec": recommendation,
            "Color": color
        }

    except Exception as e:
        # console.print(f"[red]Error processing {filepath}: {e}[/red]")
        return None

def main():
    console.print("[bold blue]Analyzing TCGPlayer Data...[/bold blue]")
    
    files = glob.glob("*.csv")
    results = []
    
    for f in files:
        # Skip aggregate files
        if "price_history" in f or "card_prices" in f:
            continue
            
        res = analyze_file(f)
        if res:
            results.append(res)

    # Sort by recommendation priority (Buy > Sell > Hold)
    # Custom sort: Buy=0, Sell=1, Hold=2
    def sort_key(x):
        if "BUY" in x["Rec"]: return 0
        if "SELL" in x["Rec"]: return 1
        return 2

    results.sort(key=sort_key)

    table = Table(title="TCGPlayer Market Analysis", box=box.ROUNDED)
    table.add_column("Product", style="cyan", no_wrap=True)
    table.add_column("Price", justify="right", style="green")
    table.add_column("7d Change", justify="right")
    table.add_column("30d Change", justify="right")
    table.add_column("Recommendation", justify="center")

    for r in results:
        c7 = f"[green]+{r['7d %']:.1f}%[/green]" if r['7d %'] > 0 else f"[red]{r['7d %']:.1f}%[/red]"
        c30 = f"[green]+{r['30d %']:.1f}%[/green]" if r['30d %'] > 0 else f"[red]{r['30d %']:.1f}%[/red]"
        
        rec_str = f"[{r['Color']}]{r['Rec']}[/{r['Color']}]"
        
        table.add_row(
            r["Product"],
            f"${r['Price']:.2f}",
            c7,
            c30,
            rec_str
        )

    console.print(table)

if __name__ == "__main__":
    main()
