import math

# 1. Mock normalize_direction
def normalize_direction(direction: str) -> str:
    d = str(direction).lower().strip()
    if d in ("up", "bullish", "long", "buy"): return "long"
    if d in ("down", "bearish", "short", "sell"): return "short"
    return "neutral"

# 2. Mock calculate_stop_loss / calculate_take_profit
def calculate_stop_loss(entry_price, atr, direction, multiplier=2.0):
    distance = atr * multiplier
    if direction == "short":
        return entry_price + distance
    return entry_price - distance

def calculate_take_profit(entry_price, atr, direction, multiplier=4.0):
    distance = atr * multiplier
    if direction == "short":
        return entry_price - distance
    return entry_price + distance

# 3. Mock check_drawdown with new logic
def check_drawdown(current_pnl, peak_pnl, new_trade_risk, max_daily_loss_pct=5.0):
    baseline = max(peak_pnl, 1000.0)
    projected_loss = current_pnl - new_trade_risk
    drawdown_abs = peak_pnl - projected_loss
    limit_abs = baseline * (max_daily_loss_pct / 100.0)
    return drawdown_abs <= limit_abs

# 4. Mock calculate_confidence (Setup Score)
def calculate_confidence(htf_aligned, trade_direction, htf_bias):
    score = 0.8 # Base
    if not htf_aligned:
        score -= 0.3
    if htf_bias != "neutral" and trade_direction != htf_bias:
        score -= 0.2
    return max(0.0, score)

def verify():
    print("=== Standalone Verification of Logic ===")
    
    # 1. Directions
    print("\n1. Directions:")
    for d in ["up", "down", "bullish", "bearish", "long", "short"]:
        print(f"  {d:10} -> {normalize_direction(d)}")
        
    # 2. SL/TP for Short
    print("\n2. Short SL/TP (Entry 50000, ATR 1000):")
    entry, atr = 50000.0, 1000.0
    sl = calculate_stop_loss(entry, atr, "short")
    tp = calculate_take_profit(entry, atr, "short")
    print(f"  SL: {sl} (should be 52000)")
    print(f"  TP: {tp} (should be 46000)")
    
    # 3. Drawdown (Cold Start)
    print("\n3. Drawdown (Cold Start, PnL -50, Peak 0, Risk 20):")
    # limit = 1000 * 0.05 = 50. 
    # current drawdown = 0 - (-50 - 20) = 70. 
    # 70 > 50 -> should fail.
    res = check_drawdown(-50.0, 0.0, 20.0)
    print(f"  Check Result: {'Passed' if res else 'Failed (Correct)'}")
    
    # 4. Setup Score
    print("\n4. Setup Score:")
    s1 = calculate_confidence(True, "long", "long")
    s2 = calculate_confidence(False, "long", "short")
    print(f"  Aligned: {s1:.2f}")
    print(f"  Misaligned: {s2:.2f}")
    
    print("\n=== Verification Completed ===")

if __name__ == "__main__":
    verify()
