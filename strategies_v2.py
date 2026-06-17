import pandas as pd
import numpy as np
from ta.trend import EMAIndicator
from ta.volatility import AverageTrueRange

from Core.gann_analysis import GannAnalyzer

class InstitutionalStrategiesV2:
    def __init__(self):
        self.gann = GannAnalyzer()

    def detect_order_blocks(self, df: pd.DataFrame):
        """كشف كتل الطلب (Order Blocks) - مناطق تجمع سيولة المؤسسات"""
        # منطق مبسط: آخر شمعة هابطة قبل حركة صعودية قوية (أو العكس)
        df['body_size'] = abs(df['close'] - df['open'])
        df['is_bullish'] = df['close'] > df['open']
        
        # كشف Bullish Order Block
        last_bear_idx = df[~df['is_bullish']].index[-1]
        following_bulls = df.loc[last_bear_idx+1:].is_bullish.all()
        
        if following_bulls and df.loc[last_bear_idx+1:].body_size.sum() > df.loc[last_bear_idx].body_size * 2:
            return {"type": "BULLISH_OB", "price": df.loc[last_bear_idx].close}
        return None

    def check_market_structure(self, df: pd.DataFrame):
        """تحليل هيكلية السوق (Market Structure) - BOS/CHoCH"""
        highs = df['high'].rolling(window=5).max()
        lows = df['low'].rolling(window=5).min()
        
        current_close = df['close'].iloc[-1]
        prev_high = highs.iloc[-6]
        
        if current_close > prev_high:
            return "BOS_UP" # Break of Structure to the upside
        return "NEUTRAL"

    def calculate_combined_score(self, df: pd.DataFrame, df_higher: pd.DataFrame = None) -> dict:
        score = 0
        report = []
        
        # 0. Multi-Timeframe Bias (MTF) - الثعلب المؤسسي يبدأ من الفريم الأكبر
        if df_higher is not None:
            higher_ema200 = EMAIndicator(df_higher['close'], window=200).ema_indicator().iloc[-1]
            if df_higher['close'].iloc[-1] > higher_ema200:
                score += 20
                report.append("Higher TF Bias: Bullish (+20)")
            else:
                score -= 20
                report.append("Higher TF Bias: Bearish (-20)")

        # 1. Market Structure (30 pts)
        structure = self.check_market_structure(df)
        if structure == "BOS_UP":
            score += 30
            report.append("Market Structure: Bullish BOS (+30)")
            
        # 2. Order Block & Liquidity (25 pts)
        ob = self.detect_order_blocks(df)
        if ob and ob["type"] == "BULLISH_OB":
            # التحقق مما إذا كان السعر الحالي قريباً من الـ OB (منطقة الطلب)
            current_price = df['close'].iloc[-1]
            if abs(current_price - ob["price"]) / current_price < 0.01:
                score += 35 # زيادة النقاط لقرب السعر من منطقة المؤسسات
                report.append("Price in Institutional Demand Zone (+35)")
            else:
                score += 25
                report.append("Institutional Order Block Detected (+25)")
            
        # 3. Trend Alignment (20 pts)
        ema200 = EMAIndicator(df['close'], window=200).ema_indicator().iloc[-1]
        if df['close'].iloc[-1] > ema200:
            score += 20
            report.append("Above Institutional EMA 200 (+20)")

        # 4. Volatility Filter (10 pts)
        atr = AverageTrueRange(df['high'], df['low'], df['close']).average_true_range().iloc[-1]
        atr_pct = (atr / df['close'].iloc[-1]) * 100
        if 0.5 < atr_pct < 2.5:
            score += 10
            report.append("Volatility: Optimal (+10)")

        # 5. Gann Analysis (15 pts)
        gann_bias = self.gann.get_gann_bias(df)
        if gann_bias == "BULLISH_CONTINUATION":
            score += 15
            report.append("Gann Square of 9: Bullish Bias (+15)")
        elif gann_bias == "BEARISH_REVERSAL_ZONE":
            score -= 30
            report.append("Gann Alert: Reversal Zone Detected (-30)")

        return {
            "total_score": score,
            "report": " | ".join(report),
            "market_state": structure,
            "quality_score": 100 if score > 50 else 50
        }

    def get_trade_params(self, df: pd.DataFrame):
        price = df['close'].iloc[-1]
        atr = AverageTrueRange(df['high'], df['low'], df['close']).average_true_range().iloc[-1]
        
        # إدارة مخاطر مؤسسية: SL تحت أقرب قاع فني
        sl = price - (atr * 1.5)
        tp = price + (atr * 3) # R:R 1:2
        
        return {"entry": price, "sl": sl, "tp": tp, "atr": atr}
