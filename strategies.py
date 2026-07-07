import pandas as pd
import numpy as np
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange, BollingerBands
from ta.volume import OnBalanceVolumeIndicator

class InstitutionalStrategies:
    def __init__(self):
        pass

    def classify_market(self, df: pd.DataFrame) -> dict:
        """تصنيف السوق مع استخراج القيم الرقمية للتشخيص"""
        if len(df) < 200: return {"state": "Low Data", "confidence": 0, "values": {}}
        
        close = df['close'].iloc[-1]
        
        # حساب المتوسطات
        ema50_series = EMAIndicator(df['close'], window=50).ema_indicator()
        ema50 = ema50_series.iloc[-1]
        ema200 = EMAIndicator(df['close'], window=200).ema_indicator().iloc[-1]
        
        # حساب ADX لقوة الترند
        adx_ind = ADXIndicator(df['high'], df['low'], df['close'])
        adx = adx_ind.adx().iloc[-1]
        
        # حساب الانحراف المعياري
        rolling_20 = df['close'].rolling(20)
        std_dev = rolling_20.std().iloc[-1]
        avg_price = rolling_20.mean().iloc[-1]
        volatility_ratio = (std_dev / avg_price) * 100
        
        atr = AverageTrueRange(df['high'], df['low'], df['close']).average_true_range().iloc[-1]
        
        values = {
            "EMA50": round(ema50, 2),
            "EMA200": round(ema200, 2),
            "ADX": round(adx, 2),
            "Volatility %": round(volatility_ratio, 4),
            "ATR": round(atr, 6),
            "Close": round(close, 2)
        }

        # تمييز السوق
        if volatility_ratio < 0.5:
            state = "Low Volatility Range"
            reason = "Volatility ratio is below 0.5%, indicating a tight range."
        elif close > ema50 > ema200 and adx > 25:
            state = "Strong Uptrend"
            reason = "Price is above EMA50/200 and ADX > 25, showing strong momentum."
        elif close < ema50 < ema200 and adx > 25:
            state = "Strong Downtrend"
            reason = "Price is below EMA50/200 and ADX > 25, showing strong downward pressure."
        elif abs(close - ema200) / ema200 < 0.01:
            state = "Distribution/Accumulation"
            reason = "Price is hovering within 1% of EMA200, suggesting a phase shift."
        else:
            state = "Sideways/Neutral"
            reason = "No clear trend alignment or volatility breakout detected."

        return {"state": state, "confidence": 80, "values": values, "reason": reason}

    def get_indicators_data(self, df: pd.DataFrame) -> dict:
        """جمع كافة القيم الرقمية للمؤشرات المطلوبة"""
        close = df['close']
        high = df['high']
        low = df['low']
        volume = df['volume']

        rsi = RSIIndicator(close).rsi().iloc[-1]
        macd_ind = MACD(close)
        macd = macd_ind.macd().iloc[-1]
        bb = BollingerBands(close)
        atr = AverageTrueRange(high, low, close).average_true_range().iloc[-1]
        obv = OnBalanceVolumeIndicator(close, volume).on_balance_volume().iloc[-1]
        
        avg_vol = volume.rolling(20).mean().iloc[-1]
        rel_vol = volume.iloc[-1] / avg_vol if avg_vol > 0 else 0

        return {
            "RSI": round(rsi, 2),
            "MACD": round(macd, 6),
            "ATR": round(atr, 6),
            "ATR %": round((atr/close.iloc[-1])*100, 4),
            "BB Upper": round(bb.bollinger_hband().iloc[-1], 2),
            "BB Lower": round(bb.bollinger_lband().iloc[-1], 2),
            "OBV": round(obv, 0),
            "Rel Volume": round(rel_vol, 2),
            "EMA200 Dist %": round(abs(close.iloc[-1] - EMAIndicator(close, window=200).ema_indicator().iloc[-1])/close.iloc[-1]*100, 2)
        }

    def get_smc_data(self, df: pd.DataFrame) -> dict:
        """تحليل مفاهيم الأموال الذكية (SMC) واستخراج القيم"""
        last_50 = df.iloc[-50:]
        highest_high = last_50['high'].max()
        lowest_low = last_50['low'].min()
        curr_close = df['close'].iloc[-1]
        
        # البحث عن FVG (Fair Value Gap) بسيط
        fvg = "None"
        if len(df) > 3:
            # Bullish FVG: Low of candle 3 > High of candle 1
            if df['low'].iloc[-1] > df['high'].iloc[-3]:
                fvg = f"Bullish Gap ({round(df['high'].iloc[-3], 2)} - {round(df['low'].iloc[-1], 2)})"
            # Bearish FVG: High of candle 3 < Low of candle 1
            elif df['high'].iloc[-1] < df['low'].iloc[-3]:
                fvg = f"Bearish Gap ({round(df['low'].iloc[-3], 2)} - {round(df['high'].iloc[-1], 2)})"

        # تتبع القمم والقيعان (BOS/CHOCH)
        structure = "Neutral"
        if curr_close > highest_high * 0.99: structure = "Bullish BOS Potential"
        elif curr_close < lowest_low * 1.01: structure = "Bearish BOS Potential"

        return {
            "Structure": structure,
            "FVG": fvg,
            "Liquidity Sweep": "Detected" if (df['high'].iloc[-1] > highest_high or df['low'].iloc[-1] < lowest_low) else "None",
            "Imbalance": "Yes" if fvg != "None" else "No",
            "Order Block": "Testing" if abs(curr_close - lowest_low)/lowest_low < 0.005 else "Scanning"
        }

    def calculate_combined_score(self, df: pd.DataFrame, df_higher: pd.DataFrame = None) -> dict:
        """نظام التقييم المطور مع دعم الـ Logging الاحترافي"""
        score = 0
        reasons = []
        
        # 1. Regime Analysis
        regime = self.classify_market(df)
        if regime["state"] == "Strong Uptrend":
            score += 40
            reasons.append("Strong Trend Alignment (+40)")
        elif regime["state"] == "Low Volatility Range":
            score += 10
            reasons.append("Consolidation Phase (+10)")
            
        # 2. Indicators
        inds = self.get_indicators_data(df)
        if 40 < inds["RSI"] < 70:
            score += 10
            reasons.append("Healthy RSI (+10)")
        if inds["Rel Volume"] > 1.2:
            score += 15
            reasons.append("Volume Confirmation (+15)")
            
        # 3. SMC
        smc = self.get_smc_data(df)
        if smc["FVG"] != "None" and "Bullish" in smc["FVG"]:
            score += 20
            reasons.append("Bullish FVG Detected (+20)")
            
        # 4. MTF
        htf_info = {"supported": False, "reason": "No HTF Data"}
        if df_higher is not None:
            htf_regime = self.classify_market(df_higher)
            if "Uptrend" in htf_regime["state"]:
                score += 15
                htf_info = {"supported": True, "reason": "HTF Trend is Bullish", "Trend": htf_regime["state"]}
            else:
                score -= 20
                htf_info = {"supported": False, "reason": f"HTF Trend is {htf_regime['state']}", "Trend": htf_regime["state"]}
            # إضافة قيم HTF للتشخيص
            for k, v in htf_regime["values"].items(): htf_info[f"HTF {k}"] = v

        quality = 100
        if inds["Rel Volume"] < 0.5: quality -= 40
        if inds["ATR %"] > 5: quality -= 30

        return {
            "total_score": max(0, score),
            "quality_score": quality,
            "reasons": reasons,
            "regime_data": regime,
            "indicators_data": inds,
            "smc_data": smc,
            "htf_data": htf_info,
            "verdict": "BUY" if score >= 75 and quality >= 60 else "SKIP"
        }

    def get_trade_params(self, df: pd.DataFrame):
        price = df['close'].iloc[-1]
        atr = AverageTrueRange(df['high'], df['low'], df['close']).average_true_range().iloc[-1]
        local_low = df['low'].iloc[-20:].min()
        sl = min(local_low, price - (atr * 1.5))
        if (price - sl) / price > 0.05: sl = price * 0.95
        risk = price - sl
        tp = price + (risk * 2)
        recent_high = df['high'].iloc[-100:].max()
        if tp > recent_high * 1.1: tp = recent_high
        return {
            "entry": price, "sl": round(sl, 8), "tp": round(tp, 8), 
            "atr": atr, "rr": round((tp - price) / (price - sl), 2) if (price - sl) > 0 else 0
        }
