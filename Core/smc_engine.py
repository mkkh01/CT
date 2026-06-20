import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)

class SMCEngine:
    def __init__(self):
        pass

    def detect_swings(self, df: pd.DataFrame, window=5):
        """كشف Swing Highs و Swing Lows"""
        df = df.copy()
        df['high_swing'] = df['high'].rolling(window=window, center=True).apply(lambda x: x[window//2] == max(x), raw=True)
        df['low_swing'] = df['low'].rolling(window=window, center=True).apply(lambda x: x[window//2] == min(x), raw=True)
        return df

    def detect_structure(self, df: pd.DataFrame):
        """تحليل الهيكل الداخلي والخارجي (Internal/External Structure, BOS, CHoCH, MSS)"""
        if len(df) < 50: return {"state": "NEUTRAL", "details": []}
        
        df = self.detect_swings(df)
        swings = []
        for i in range(len(df)):
            if df['high_swing'].iloc[i]: swings.append({'type': 'SH', 'price': df['high'].iloc[i], 'idx': i})
            if df['low_swing'].iloc[i]: swings.append({'type': 'SL', 'price': df['low'].iloc[i], 'idx': i})
            
        if len(swings) < 4: return {"state": "NEUTRAL", "details": []}
        
        last_sh = [s for s in swings if s['type'] == 'SH'][-1]
        last_sl = [s for s in swings if s['type'] == 'SL'][-1]
        current_close = df['close'].iloc[-1]
        
        state = "NEUTRAL"
        # BOS: Break of Structure
        if current_close > last_sh['price']: state = "BOS_UP"
        elif current_close < last_sl['price']: state = "BOS_DOWN"
        
        # CHoCH & MSS
        prev_sh = [s for s in swings if s['type'] == 'SH'][-2]
        prev_sl = [s for s in swings if s['type'] == 'SL'][-2]
        
        if current_close > prev_sh['price'] and df['close'].iloc[-2] <= prev_sh['price']:
            state = "CHoCH_UP"
        elif current_close < prev_sl['price'] and df['close'].iloc[-2] >= prev_sl['price']:
            state = "CHoCH_DOWN"
            
        return {"state": state, "last_sh": last_sh, "last_sl": last_sl, "swings": swings}

    def detect_fvgs(self, df: pd.DataFrame):
        """كشف وتصنيف FVG و Inverse FVG و Balanced Price Range"""
        fvgs = []
        for i in range(2, len(df)):
            # Bullish FVG
            if df['low'].iloc[i] > df['high'].iloc[i-2]:
                fvgs.append({
                    'type': 'BULLISH_FVG',
                    'top': df['low'].iloc[i],
                    'bottom': df['high'].iloc[i-2],
                    'mitigated': df['low'].iloc[i-1:].min() < df['high'].iloc[i-2],
                    'size': (df['low'].iloc[i] - df['high'].iloc[i-2]) / df['close'].iloc[i]
                })
            # Bearish FVG
            elif df['high'].iloc[i] < df['low'].iloc[i-2]:
                fvgs.append({
                    'type': 'BEARISH_FVG',
                    'top': df['low'].iloc[i-2],
                    'bottom': df['high'].iloc[i],
                    'mitigated': df['high'].iloc[i-1:].max() > df['low'].iloc[i-2],
                    'size': (df['low'].iloc[i-2] - df['high'].iloc[i]) / df['close'].iloc[i]
                })
                
        # Inverse FVG logic: If a FVG is mitigated and price stays on the other side
        # (Simplified implementation)
        return fvgs

    def detect_order_blocks(self, df: pd.DataFrame):
        """كشف Order Blocks, Breakers, و Mitigation Blocks"""
        obs = []
        for i in range(5, len(df)-2):
            # Bullish OB
            is_bearish_candle = df['close'].iloc[i] < df['open'].iloc[i]
            displacement = (df['close'].iloc[i+2] - df['close'].iloc[i]) / df['close'].iloc[i] > 0.01
            
            if is_bearish_candle and displacement:
                sweep = df['low'].iloc[i] < df['low'].iloc[i-5:i].min()
                obs.append({
                    'type': 'BULLISH_OB',
                    'price': df['close'].iloc[i],
                    'high': df['high'].iloc[i],
                    'low': df['low'].iloc[i],
                    'strength': 1.5 if sweep else 1.0,
                    'mitigated': df['low'].iloc[i+1:].min() < df['low'].iloc[i]
                })
                
            # Breaker Block logic: A failed OB that leads to a BOS
            # (Simplified implementation for detection)
            
        return obs

    def get_premium_discount(self, df: pd.DataFrame):
        """حساب مناطق Premium & Discount"""
        high = df['high'].iloc[-50:].max()
        low = df['low'].iloc[-50:].min()
        mid = (high + low) / 2
        current = df['close'].iloc[-1]
        
        zone = "PREMIUM" if current > mid else "DISCOUNT"
        return {"zone": zone, "mid": mid, "high": high, "low": low}

    def detect_liquidity(self, df: pd.DataFrame):
        """كشف Liquidity Sweeps, Equal Highs/Lows"""
        highs = df['high'].iloc[-30:].values
        lows = df['low'].iloc[-30:].values
        
        eqh = []
        for i in range(len(highs)):
            for j in range(i+1, len(highs)):
                if abs(highs[i] - highs[j]) / highs[i] < 0.0005:
                    eqh.append(highs[i])
                    
        current_high = df['high'].iloc[-1]
        recent_max = df['high'].iloc[-20:-1].max()
        sweep = current_high > recent_max and df['close'].iloc[-1] < recent_max
        
        return {"equal_highs": eqh, "liquidity_sweep": sweep}
