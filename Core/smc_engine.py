import pandas as pd
import numpy as np

class SMCEngine:
    def __init__(self):
        pass

    def detect_structure(self, df: pd.DataFrame, window=5):
        """كشف بنية السوق (BOS, CHoCH, MSS)"""
        df = df.copy()
        df['high_swing'] = df['high'].rolling(window=window, center=True).apply(lambda x: x[window//2] == max(x), raw=True)
        df['low_swing'] = df['low'].rolling(window=window, center=True).apply(lambda x: x[window//2] == min(x), raw=True)
        
        swings = []
        for i in range(len(df)):
            if df['high_swing'].iloc[i]:
                swings.append({'type': 'HH', 'price': df['high'].iloc[i], 'index': i})
            if df['low_swing'].iloc[i]:
                swings.append({'type': 'LL', 'price': df['low'].iloc[i], 'index': i})
        
        structure = "NEUTRAL"
        if len(swings) >= 2:
            last = swings[-1]
            prev = swings[-2]
            current_price = df['close'].iloc[-1]
            
            if last['type'] == 'HH' and current_price > last['price']:
                structure = "BOS_UP"
            elif last['type'] == 'LL' and current_price < last['price']:
                structure = "BOS_DOWN"
            
            # CHoCH logic (Change of Character)
            if len(swings) >= 4:
                if swings[-1]['type'] == 'HH' and swings[-3]['type'] == 'HH' and swings[-1]['price'] < swings[-3]['price']:
                    structure = "CHoCH_DOWN"
                elif swings[-1]['type'] == 'LL' and swings[-3]['type'] == 'LL' and swings[-1]['price'] > swings[-3]['price']:
                    structure = "CHoCH_UP"
                    
        return structure

    def detect_fvg(self, df: pd.DataFrame):
        """كشف فجوات القيمة العادلة (Fair Value Gap)"""
        fvgs = []
        for i in range(2, len(df)):
            # Bullish FVG (Gap between Low of candle i and High of candle i-2)
            if df['low'].iloc[i] > df['high'].iloc[i-2]:
                fvgs.append({
                    'type': 'BULLISH',
                    'top': df['low'].iloc[i],
                    'bottom': df['high'].iloc[i-2],
                    'size': df['low'].iloc[i] - df['high'].iloc[i-2],
                    'index': i-1
                })
            # Bearish FVG
            elif df['high'].iloc[i] < df['low'].iloc[i-2]:
                fvgs.append({
                    'type': 'BEARISH',
                    'top': df['low'].iloc[i-2],
                    'bottom': df['high'].iloc[i],
                    'size': df['low'].iloc[i-2] - df['high'].iloc[i],
                    'index': i-1
                })
        return fvgs

    def detect_order_blocks(self, df: pd.DataFrame):
        """كشف كتل الطلب والعرض (Order Blocks) الاحترافية"""
        obs = []
        for i in range(1, len(df)-1):
            # Bullish OB: Last bearish candle before a strong move up (Displacement)
            if df['close'].iloc[i] < df['open'].iloc[i]:
                move_up = (df['close'].iloc[i+1] - df['close'].iloc[i]) / df['close'].iloc[i]
                if move_up > 0.01: # 1% displacement
                    obs.append({
                        'type': 'BULLISH_OB',
                        'price': df['close'].iloc[i],
                        'high': df['high'].iloc[i],
                        'low': df['low'].iloc[i],
                        'volume': df['volume'].iloc[i],
                        'mitigated': False
                    })
        return obs

    def detect_liquidity_sweeps(self, df: pd.DataFrame):
        """كشف سحب السيولة (Liquidity Sweeps)"""
        sweeps = []
        if len(df) < 20: return sweeps
        
        recent_high = df['high'].iloc[-20:-1].max()
        recent_low = df['low'].iloc[-20:-1].min()
        
        current_high = df['high'].iloc[-1]
        current_low = df['low'].iloc[-1]
        current_close = df['close'].iloc[-1]
        
        # Sweep above high then close below (Stop Hunt)
        if current_high > recent_high and current_close < recent_high:
            sweeps.append({'type': 'BUY_SIDE_SWEEP', 'price': recent_high})
            
        # Sweep below low then close above
        if current_low < recent_low and current_close > recent_low:
            sweeps.append({'type': 'SELL_SIDE_SWEEP', 'price': recent_low})
            
        return sweeps
