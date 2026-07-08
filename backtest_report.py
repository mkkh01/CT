import pandas as pd
import numpy as np
from strategies import InstitutionalStrategies
import yfinance as yf


def run_backtest(symbol: str = "BTC-USD", capital: float = 1000.0,
                 risk_per_trade_pct: float = 1.0):
    print(f"📊 Starting Backtest for {symbol} (Capital: ${capital:.0f})...")
    print("=" * 55)

    data = yf.download(symbol, period="1mo", interval="1h")
    if data.empty:
        print("❌ Failed to fetch data")
        return

    df = data.copy()
    df.columns = [col[0].lower() if isinstance(col, tuple) else col.lower()
                  for col in df.columns]

    strat = InstitutionalStrategies()
    min_candles = max(strat.cfg.min_candles_ltf, 200)
    trades = []
    equity_curve = []

    for i in range(min_candles, len(df)):
        test_df = df.iloc[:i].copy()
        htf_df = test_df.iloc[::4].copy() if len(test_df) >= 4 else None
        analysis = strat.analyze(test_df, df_htf=htf_df, symbol=symbol)

        if analysis["verdict"] in {"BUY", "SELL"}:
            params = strat.get_trade_params(test_df, side=analysis["verdict"])
            if params["rr"] < strat.cfg.rr_min:
                continue

            entry = params["entry"]
            sl = params["stop"]
            tp = params["target"]
            risk_amount = capital * (risk_per_trade_pct / 100)
            position_size = risk_amount / abs(entry - sl) if abs(entry - sl) > 0 else 0

            # Forward-walk to find exit (TP or SL hit first)
            exit_price = None
            exit_idx = None
            for j in range(i + 1, min(i + 100, len(df))):
                future_high = df["high"].iloc[j]
                future_low = df["low"].iloc[j]
                if analysis["verdict"] == "BUY":
                    if future_high >= tp:
                        exit_price = tp
                        exit_idx = j
                        break
                    elif future_low <= sl:
                        exit_price = sl
                        exit_idx = j
                        break
                else:  # SELL
                    if future_low <= tp:
                        exit_price = tp
                        exit_idx = j
                        break
                    elif future_high >= sl:
                        exit_price = sl
                        exit_idx = j
                        break

            if exit_price is None:
                continue  # trade never closed in lookahead window

            # Calculate actual PnL
            if analysis["verdict"] == "BUY":
                pnl = (exit_price - entry) * position_size
                pnl_pct = ((exit_price / entry) - 1) * 100
                won = exit_price >= entry
            else:
                pnl = (entry - exit_price) * position_size
                pnl_pct = ((entry / exit_price) - 1) * 100
                won = exit_price <= entry

            capital += pnl
            trades.append({
                "entry_time": df.index[i],
                "exit_time": df.index[exit_idx],
                "type": analysis["verdict"],
                "entry": entry,
                "exit": exit_price,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "won": won,
                "score": analysis["total_score"],
                "rr": params["rr"],
            })
            equity_curve.append(capital)

    # ── Results ──
    total = len(trades)
    wins = sum(1 for t in trades if t["won"])
    losses = total - wins
    win_rate = (wins / total * 100) if total > 0 else 0
    gross_profit = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    gross_loss = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
    net_pnl = gross_profit - gross_loss
    avg_rr = np.mean([t["rr"] for t in trades]) if trades else 0
    avg_score = np.mean([t["score"] for t in trades]) if trades else 0

    # Max drawdown from equity curve
    peak = 1000.0
    max_dd = 0.0
    for eq in equity_curve:
        peak = max(peak, eq)
        dd = (peak - eq) / peak * 100
        max_dd = max(max_dd, dd)

    print(f"\n✅ Backtest Completed — {symbol}")
    print("=" * 55)
    print(f"  Period:             {df.index[0]} → {df.index[-1]}")
    print(f"  Total Candles:      {len(df)}")
    print(f"  Trades Found:       {total}")
    print(f"  ──────────────────────────────────")
    print(f"  Win Rate:           {win_rate:.1f}%  ({wins}W / {losses}L)")
    print(f"  Gross Profit:       ${gross_profit:+.2f}")
    print(f"  Gross Loss:         ${gross_loss:.2f}")
    print(f"  Net PnL:            ${net_pnl:+.2f}")
    print(f"  Profit Factor:      {gross_profit/max(gross_loss,0.01):.2f}")
    print(f"  Average RR:         1:{avg_rr:.1f}")
    print(f"  Average Score:      {avg_score:.1f}/100")
    print(f"  Max Drawdown:       {max_dd:.1f}%")
    print(f"  Final Capital:      ${equity_curve[-1]:.2f}" if equity_curve else "  No equity curve")

    if trades:
        res_df = pd.DataFrame(trades)
        print(f"\n  Sample Trades (first 10):")
        print(f"  {'Entry':<20} {'Type':<6} {'Entry':<12} {'Exit':<12} {'PnL':<10} {'Won':<5}")
        print(f"  {'-'*70}")
        for t in trades[:10]:
            print(f"  {str(t['entry_time']):<20} {t['type']:<6} {t['entry']:<12.4f} {t['exit']:<12.4f} {t['pnl']:<+10.2f} {'✅' if t['won'] else '❌':<5}")
    else:
        print("  🚫 No trades met the strict institutional criteria.")


if __name__ == "__main__":
    run_backtest()
