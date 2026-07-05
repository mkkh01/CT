import pandas as pd
import numpy as np
from ta.trend import EMAIndicator, MACD
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange, BollingerBands

class InstitutionalStrategies:
    def __init__(self):
        pass

    def classify_market(self, df: pd.DataFrame) -> dict:
        """تصنيف السوق - إصلاح جذري للتمييز بين الترند والتوزيع والسوق العرضي"""
        if len(df) < 200: return {"state": "Low Data", "confidence": 0}
        
        close = df['close'].iloc[-1]
        ema50 = EMAIndicator(df['close'], window=50).ema_indicator().iloc[-1]
        ema200 = EMAIndicator(df['close'], window=200).ema_indicator().iloc[-1]
        atr = AverageTrueRange(df['high'], df['low'], df['close']).average_true_range().iloc[-1]
        
        # حساب الانحراف المعياري لتمييز السوق العرضي
        std_dev = df['close'].rolling(20).std().iloc[-1]
        avg_price = df['close'].rolling(20).mean().iloc[-1]
        volatility_ratio = (std_dev / avg_price) * 100
        
        # تمييز السوق العرضي (Ranging)
        if volatility_ratio < 0.5:
            return {"state": "Low Volatility Range", "confidence": 95}

        # تمييز الترند الحقيقي (Alignment)
        if close > ema50 > ema200:
            # التحقق من ميل المتوسطات (Slope)
            ema50_prev = EMAIndicator(df['close'], window=50).ema_indicator().iloc[-5]
            if ema50 > ema50_prev:
                return {"state": "Strong Uptrend", "confidence": 90}
            else:
                return {"state": "Exhausted Uptrend", "confidence": 80}
        
        elif close < ema50 < ema200:
            ema50_prev = EMAIndicator(df['close'], window=50).ema_indicator().iloc[-5]
            if ema50 < ema50_prev:
                return {"state": "Strong Downtrend", "confidence": 90}
            else:
                return {"state": "Exhausted Downtrend", "confidence": 80}

        # تمييز التوزيع (Distribution/Accumulation)
        # إذا كان السعر يتذبذب حول EMA200
        ema200_dist = abs(close - ema200) / ema200
        if ema200_dist < 0.01:
            return {"state": "Distribution Phase", "confidence": 85}

        return {"state": "Sideways/Unclear", "confidence": 70}

    def get_market_quality_score(self, df: pd.DataFrame) -> float:
        """فلتر جودة السوق (Market Quality Score)"""
        # حساب السيولة والحجم والتذبذب
        avg_vol = df['volume'].rolling(20).mean().iloc[-1]
        curr_vol = df['volume'].iloc[-1]
        atr = AverageTrueRange(df['high'], df['low'], df['close']).average_true_range().iloc[-1]
        
        score = 100
        if curr_vol < avg_vol * 0.5: score -= 30 # سيولة منخفضة
        if atr / df['close'].iloc[-1] > 0.03: score -= 20 # تذبذب خطر
        
        return max(0, score)

    def calculate_combined_score(self, df: pd.DataFrame, df_higher: pd.DataFrame = None) -> dict:
        """نظام التقييم بالنقاط المطور - إلغاء النقاط الافتراضية والتركيز على التأكيد الفعلي"""
        score = 0
        report = []
        
        # 1. Trend & Context (30 pts)
        market = self.classify_market(df)
        if market["state"] == "Strong Uptrend":
            score += 30
            report.append(f"Trend: Strong Uptrend (+30)")
        elif market["state"] == "Strong Downtrend":
            # حالياً النظام يدعم الشراء فقط، لذا الترند الهابط يعطي 0 أو نقاط سالبة
            score -= 20
            report.append("Trend: Strong Downtrend (-20)")
        else:
            report.append(f"Trend: {market['state']} (0)")
            
        # 2. Market Structure (20 pts) - قمم وقيعان صاعدة
        last_lows = df['low'].rolling(20).min()
        if df['low'].iloc[-1] > last_lows.iloc[-10]:
            score += 20
            report.append("Structure: Higher Lows (+20)")
        else:
            report.append("Structure: Broken/Neutral (0)")
            
        # 3. Volume Confirmation (15 pts) - تأكيد مؤسسي
        avg_vol = df['volume'].rolling(20).mean().iloc[-1]
        if df['volume'].iloc[-1] > avg_vol * 1.5:
            score += 15
            report.append("Volume: Institutional Surge (+15)")
        
        # 4. S/R & Liquidity (20 pts) - حساب حقيقي للدعم والمقاومة
        recent_high = df['high'].iloc[-50:-1].max()
        recent_low = df['low'].iloc[-50:-1].min()
        price = df['close'].iloc[-1]
        
        # منع الشراء قرب المقاومة
        dist_to_high = (recent_high - price) / price
        if dist_to_high < 0.005: # أقل من 0.5% من القمة
            score -= 30
            report.append("Risk: Near Resistance (-30)")
        elif price > recent_low and (price - recent_low)/price < 0.01:
            score += 20
            report.append("S/R: Near Support Confirmation (+20)")
        
        # 5. Multi Timeframe (15 pts) - إلزامي للدرجات العالية
        if df_higher is not None:
            higher_market = self.classify_market(df_higher)
            if higher_market["state"] == "Strong Uptrend":
                score += 15
                report.append("MTF: Bullish Context (+15)")
            elif "Downtrend" in higher_market["state"]:
                score -= 25
                report.append("MTF: Bearish Context (-25)")

        return {
            "total_score": max(0, score),
            "report": " | ".join(report),
            "market_state": market["state"],
            "quality_score": self.get_market_quality_score(df)
        }

    def get_trade_params(self, df: pd.DataFrame):
        """إدارة المخاطر - حساب الوقف والهدف بناءً على هيكل السوق والسيولة"""
        price = df['close'].iloc[-1]
        atr = AverageTrueRange(df['high'], df['low'], df['close']).average_true_range().iloc[-1]
        
        # الوقف تحت آخر قاع محلي أو ATR
        local_low = df['low'].iloc[-20:].min()
        sl = min(local_low, price - (atr * 1.5))
        
        # التأكد من أن الوقف ليس بعيداً جداً (أقصى مخاطرة 5%)
        if (price - sl) / price > 0.05:
            sl = price * 0.95
            
        # الهدف بناءً على R:R لا يقل عن 1.5
        risk = price - sl
        tp = price + (risk * 2) # نهدف لـ 1:2
        
        # التأكد من أن الهدف ليس مستحيلاً (أعلى من المقاومة القريبة بشكل مبالغ فيه)
        recent_high = df['high'].iloc[-100:].max()
        if tp > recent_high * 1.1: # إذا كان الهدف أبعد بـ 10% من القمة التاريخية
            tp = recent_high # نكتفي بالقمة السابقة كهدف أول
            
        return {
            "entry": price, 
            "sl": round(sl, 8), 
            "tp": round(tp, 8), 
            "atr": atr,
            "rr": round((tp - price) / (price - sl), 2) if (price - sl) > 0 else 0
        }
