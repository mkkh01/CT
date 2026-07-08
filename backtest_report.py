import pandas as pd
import numpy as np
from strategies import InstitutionalStrategies
import yfinance as yf


def run_backtest(symbol: str = "BTC-USD"):
    print(f"📊 Starting Backtest for {symbol}...")

    data = yf.download(symbol, period="1mo", interval="1h")
    if data.empty:
        print("❌ Failed to fetch data")
        return

    df = data.copy()
    df.columns = [col[0].lower() if isinstance(col, tuple) else col.lower() for col in df.columns]

    strat = InstitutionalStrategies()
    results = []

    for i in range(max(strat.cfg.min_candles_ltf, 200), len(df)):
        test_df = df.iloc[:i].copy()
        htf_df = test_df.iloc[::4].copy() if len(test_df) >= 4 else None
        analysis = strat.calculate_combined_score(test_df, htf_df)

        if i < max(strat.cfg.min_candles_ltf, 200) + 5:
            print(
                f"Candle {i}: Score={analysis['total_score']}, "
                f"Confidence={analysis['confidence']}, "
                f"Probability={analysis['probability']}, "
                f"Verdict={analysis['verdict']}"
            )

        if analysis["verdict"] in {"BUY", "SELL"}:
            params = strat.get_trade_params(test_df, side=analysis["verdict"])
            if params["rr"] >= strat.cfg.rr_min:
                results.append({
                    "time": df.index[i],
                    "price": params["entry"],
                    "score": analysis["total_score"],
                    "confidence": analysis["confidence"],
                    "probability": analysis["probability"],
                    "rr": params["rr"],
                    "reason": analysis["reason"],
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
