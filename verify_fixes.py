import asyncio
from datetime import datetime, timezone
from contracts.market import Candle
from contracts.config import CoinConfig
from contracts.decision import StrategySignal
from engine.orchestrator import normalize_direction
from engine.confidence import calculate_confidence
from engine.risk import assess_risk, calculate_stop_loss, calculate_take_profit, check_drawdown
from engine.market_location import is_near_resistance

async def verify_logic():
    print("=== Verification of CT Fixes ===")
    
    # 1. Verify Direction Normalization
    print("\n1. Testing Direction Normalization:")
    test_cases = ["up", "down", "bullish", "bearish", "long", "short", "neutral"]
    for tc in test_cases:
        norm = normalize_direction(tc)
        print(f"  Input: {tc:10} -> Normalized: {norm}")
    
    # 2. Verify Short Direction in Risk
    print("\n2. Testing Short Direction in Risk:")
    entry = 50000.0
    atr = 1000.0
    sl_long = calculate_stop_loss(entry, atr, "long")
    tp_long = calculate_take_profit(entry, atr, "long")
    sl_short = calculate_stop_loss(entry, atr, "short")
    tp_short = calculate_take_profit(entry, atr, "short")
    
    print(f"  Long:  Entry={entry}, SL={sl_long}, TP={tp_long} (SL < Entry < TP: {sl_long < entry < tp_long})")
    print(f"  Short: Entry={entry}, SL={sl_short}, TP={tp_short} (TP < Entry < SL: {tp_short < entry < sl_short})")
    
    # 3. Verify Setup Score (New Confidence)
    print("\n3. Testing Setup Score Calculation:")
    sig = StrategySignal(
        symbol="BTCUSDT", timeframe="15m", strategy_name="test",
        direction="long", raw_score=0.8, timestamp=datetime.now(timezone.utc),
        source_candle_open_time=datetime.now(timezone.utc)
    )
    
    # Mock HTF Result
    class MockHTF:
        def __init__(self, aligned, bias):
            self.aligned = aligned
            self.bias = bias
            self.alignment = aligned
            
    htf_aligned = MockHTF(True, "long")
    htf_misaligned = MockHTF(False, "short")
    
    score_aligned = calculate_confidence(
        signals=[sig], htf_result=htf_aligned, regime=None,
        trend_strength=0.8, momentum_score=0.8, volume_confirmation=0.8,
        session_score=0.8, symbol="BTCUSDT", trade_direction="long"
    )
    
    score_misaligned = calculate_confidence(
        signals=[sig], htf_result=htf_misaligned, regime=None,
        trend_strength=0.8, momentum_score=0.8, volume_confirmation=0.8,
        session_score=0.8, symbol="BTCUSDT", trade_direction="long"
    )
    
    print(f"  Setup Score (Aligned HTF):    {score_aligned:.4f}")
    print(f"  Setup Score (Misaligned HTF): {score_misaligned:.4f}")
    print(f"  Penalty applied: {score_aligned - score_misaligned:.4f}")

    # 4. Verify Market Location (Resistance Check)
    print("\n4. Testing Market Location:")
    levels = [51000.0, 49000.0]
    near = is_near_resistance(50950.0, levels, "long")
    far = is_near_resistance(50000.0, levels, "long")
    print(f"  Price 50950 near 51000 (Long): {near}")
    print(f"  Price 50000 far from levels:   {far}")

    # 5. Verify Drawdown Baseline
    print("\n5. Testing Drawdown Baseline:")
    # Current PnL = -50, Peak = 0, Risk = 20. 
    # Old logic would reject because peak=0. New logic uses 1000 baseline.
    dd_ok = check_drawdown(current_pnl=-50.0, peak_pnl=0.0, new_trade_risk=20.0)
    print(f"  Drawdown Check (Cold Start, -50 PnL, 20 Risk): {'Passed' if dd_ok else 'Failed'}")

    print("\n=== Verification Completed ===")

if __name__ == "__main__":
    asyncio.run(verify_logic())
