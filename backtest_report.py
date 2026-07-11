import pandas as pd
import numpy as np
from strategies import InstitutionalStrategies
import yfinance as yf
from datetime import datetime, timedelta

def run_backtest(symbol="BTC-USD"):
    print(f"📊 Starting Backtest for {symbol}...")
    
    # Download data
    data = yf.download(symbol, period="1mo", interval="1h")
    if data.empty:
        print("❌ Failed to fetch data")
        return

    # Prepare DataFrame
    df = data.copy()
    df.columns = [col[0].lower() if isinstance(col, tuple) else col.lower() for col in df.columns]
    
    strat = InstitutionalStrategies()
    results = []
    
    # Test over all available candles
    for i in range(200, len(df)):
        test_df = df.iloc[:i]
        analysis = strat.calculate_combined_score(test_df)
        
        # Log analysis for first few candles to see what's happening
        if i < 210:
            print(f"Candle {i}: Score={analysis['total_score']}, Quality={analysis['quality_score']}, State={analysis['market_state']}")

        if analysis["total_score"] >= 75 and analysis["quality_score"] >= 60:
            params = strat.get_trade_params(test_df)
            if params["rr"] >= 1.5:
                results.append({
                    "time": df.index[i],
                    "price": params["entry"],
                    "score": analysis["total_score"],
                    "rr": params["rr"],
                    "report": analysis["report"]
                })

    print(f"\n✅ Backtest Completed. Found {len(results)} potential trades.")
    if results:
        res_df = pd.DataFrame(results)
        print("\n--- Sample Trades ---")
        print(res_df.head())
    else:
        print("🚫 No trades met the strict institutional criteria.")

if __name__ == "__main__":
    run_backtest()
