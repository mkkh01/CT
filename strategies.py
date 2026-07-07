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
        if len(df) < 200: 
            return {
                "state": "Low Data", 
                "confidence": 0, 
                "values": {}, 
                "reason": "Not enough candles (minimum 200 required)",
                "others_rejected": "All systems rejected due to insufficient data."
            }
        
        close = df['close'].iloc[-1]
        
        # حساب المتوسطات
        ema20 = EMAIndicator(df['close'], window=20).ema_indicator().iloc[-1]
        ema50 = EMAIndicator(df['close'], window=50).ema_indicator().iloc[-1]
        ema100 = EMAIndicator(df['close'], window=100).ema_indicator().iloc[-1]
        ema200 = EMAIndicator(df['close'], window=200).ema_indicator().iloc[-1]
        
        # حساب ADX لقوة الترند
        adx_ind = ADXIndicator(df['high'], df['low'], df['close'])
        adx = adx_ind.adx().iloc[-1]
        
        # حساب الانحراف المعياري والتقلب
        rolling_20 = df['close'].rolling(20)
        std_dev = rolling_20.std().iloc[-1]
        avg_price = rolling_20.mean().iloc[-1]
        volatility_ratio = (std_dev / avg_price) * 100
        
        atr_ind = AverageTrueRange(df['high'], df['low'], df['close'])
        atr = atr_ind.average_true_range().iloc[-1]
        atr_pct = (atr / close) * 100
        
        # Slope calculation (simple)
        slope = (df['close'].iloc[-1] - df['close'].iloc[-5]) / 5
        
        values = {
            "EMA20": round(ema20, 2),
            "EMA50": round(ema50, 2),
            "EMA100": round(ema100, 2),
            "EMA200": round(ema200, 2),
            "ADX": round(adx, 2),
            "ATR": round(atr, 6),
            "ATR%": round(atr_pct, 4),
            "Volatility": round(volatility_ratio, 4),
            "Slope": round(slope, 6),
            "Distance EMA200": round(abs(close - ema200), 2)
        }

        others_rejected = []
        # تمييز السوق
        if volatility_ratio < 0.3: # تخفيف شرط التقلب قليلاً
            state = "Low Volatility Range"
            reason = f"Volatility ratio ({round(volatility_ratio, 2)}%) is below 0.3%, indicating a tight range."
            others_rejected.append("Strong Trend: ADX or EMA alignment not met")
        elif close > ema50 and ema50 > ema200 and adx > 20: # تخفيف شرط ADX و EMA
            state = "Strong Uptrend"
            reason = "Price is above EMA50/200 and ADX > 20, showing bullish momentum."
            others_rejected.append("Range: Volatility too high for consolidation")
        elif close < ema50 and ema50 < ema200 and adx > 20:
            state = "Strong Downtrend"
            reason = "Price is below EMA50/200 and ADX > 20, showing bearish momentum."
            others_rejected.append("Range: Volatility too high for consolidation")
        elif abs(close - ema200) / ema200 < 0.02: # زيادة النطاق إلى 2%
            state = "Distribution/Accumulation"
            reason = "Price is hovering within 2% of EMA200, suggesting a phase shift."
            others_rejected.append("Trend: No clear direction away from EMA200")
        else:
            state = "Sideways/Neutral"
            reason = "No clear trend alignment or volatility breakout detected."
            others_rejected.append("Strong Trend: Conditions not met; Range: Volatility not low enough")
    
        return {
            "state": state, 
            "confidence": 85 if state != "Sideways/Neutral" else 50, 
            "values": values, 
            "reason": reason,
            "others_rejected": " | ".join(others_rejected)
        }

    def get_indicators_data(self, df: pd.DataFrame) -> dict:
        """جمع كافة القيم الرقمية للمؤشرات المطلوبة"""
        close = df['close']
        high = df['high']
        low = df['low']
        volume = df['volume']

        rsi = RSIIndicator(close).rsi().iloc[-1]
        macd_ind = MACD(close)
        macd_val = macd_ind.macd().iloc[-1]
        macd_hist = macd_ind.macd_diff().iloc[-1]
        
        atr = AverageTrueRange(high, low, close).average_true_range().iloc[-1]
        
        avg_vol = volume.rolling(20).mean().iloc[-1]
        curr_vol = volume.iloc[-1]
        rel_vol = curr_vol / avg_vol if avg_vol > 0 else 0
        
        ema200 = EMAIndicator(close, window=200).ema_indicator().iloc[-1]

        return {
            "RSI": {
                "current": round(rsi, 2),
                "required_buy": "30~65", # توسيع النطاق
                "required_sell": "35~70",
                "status_buy": 30 < rsi < 65,
                "status_sell": 35 < rsi < 70
            },
            "MACD": {
                "current": f"Hist: {round(macd_hist, 6)}",
                "status_buy": macd_hist > -0.0001, # تخفيف الشرط
                "status_sell": macd_hist < 0.0001
            },
            "ATR %": {
                "current": round((atr/close.iloc[-1])*100, 4),
                "status": (atr/close.iloc[-1])*100 > 0.3 # تخفيف الشرط
            },
            "Volume": {
                "current": round(rel_vol, 2),
                "status": rel_vol > 1.0, # تخفيف الشرط من 1.2 إلى 1.0
                "raw": {
                    "Current": round(curr_vol, 2),
                    "Average": round(avg_vol, 2),
                    "Relative": round(rel_vol, 2)
                }
            },
            "EMA Distance": {
                "current": round(abs(close.iloc[-1] - ema200)/close.iloc[-1]*100, 2),
                "status": abs(close.iloc[-1] - ema200)/close.iloc[-1]*100 < 7 # زيادة النطاق إلى 7%
            }
        }

    def get_smc_data(self, df: pd.DataFrame) -> dict:
        """تحليل مفاهيم الأموال الذكية (SMC) واستخراج القيم"""
        last_50 = df.iloc[-50:]
        highest_high = last_50['high'].max()
        lowest_low = last_50['low'].min()
        curr_close = df['close'].iloc[-1]
        
        # FVG
        fvg_bullish = False
        fvg_bearish = False
        if len(df) > 3:
            if df['low'].iloc[-1] > df['high'].iloc[-3]:
                fvg_bullish = True
            elif df['high'].iloc[-1] < df['low'].iloc[-3]:
                fvg_bearish = True

        # BOS/CHOCH
        bos_bullish = curr_close > highest_high * 0.995
        bos_bearish = curr_close < lowest_low * 1.005
        
        # Liquidity Sweep
        liq_sweep_bullish = df['low'].iloc[-1] < lowest_low and curr_close > lowest_low
        liq_sweep_bearish = df['high'].iloc[-1] > highest_high and curr_close < highest_high

        return {
            "BOS": {"bullish": bos_bullish, "bearish": bos_bearish},
            "FVG": {"bullish": fvg_bullish, "bearish": fvg_bearish},
            "Liquidity": {"bullish": liq_sweep_bullish, "bearish": liq_sweep_bearish},
            "SupportResistance": {
                "at_support": abs(curr_close - lowest_low)/lowest_low < 0.01,
                "at_resistance": abs(curr_close - highest_high)/highest_high < 0.01
            }
        }

    def calculate_combined_score(self, df: pd.DataFrame, df_higher: pd.DataFrame = None) -> dict:
        regime = self.classify_market(df)
        inds = self.get_indicators_data(df)
        smc = self.get_smc_data(df)
        
        # التقييم للشراء (BUY)
        buy_score = 0
        buy_reasons = []
        
        if regime["state"] == "Strong Uptrend": buy_score += 25; buy_reasons.append("Trend Bullish")
        if inds["RSI"]["status_buy"]: buy_score += 15; buy_reasons.append("RSI Bullish")
        if inds["MACD"]["status_buy"]: buy_score += 10; buy_reasons.append("MACD Recovery")
        if inds["Volume"]["status"]: buy_score += 15; buy_reasons.append("Volume Confirmation")
        if smc["FVG"]["bullish"]: buy_score += 15; buy_reasons.append("Bullish FVG")
        if smc["BOS"]["bullish"]: buy_score += 10; buy_reasons.append("Bullish BOS")
        if smc["Liquidity"]["bullish"]: buy_score += 10; buy_reasons.append("Bullish Liq Sweep")
        
        # التقييم للبيع (SELL)
        sell_score = 0
        sell_reasons = []
        
        if regime["state"] == "Strong Downtrend": sell_score += 25; sell_reasons.append("Trend Bearish")
        if inds["RSI"]["status_sell"]: sell_score += 15; sell_reasons.append("RSI Bearish")
        if inds["MACD"]["status_sell"]: sell_score += 10; sell_reasons.append("MACD Rejection")
        if inds["Volume"]["status"]: sell_score += 15; sell_reasons.append("Volume Confirmation")
        if smc["FVG"]["bearish"]: sell_score += 15; sell_reasons.append("Bearish FVG")
        if smc["BOS"]["bearish"]: sell_score += 10; sell_reasons.append("Bearish BOS")
        if smc["Liquidity"]["bearish"]: sell_score += 10; sell_reasons.append("Bearish Liq Sweep")

        # HTF Filter
        htf_supported_buy = True
        htf_supported_sell = True
        htf_info = {"supported": True, "reason": "No HTF Data"}
        
        if df_higher is not None:
            htf_regime = self.classify_market(df_higher)
            htf_supported_buy = "Uptrend" in htf_regime["state"] or htf_regime["state"] == "Sideways/Neutral"
            htf_supported_sell = "Downtrend" in htf_regime["state"] or htf_regime["state"] == "Sideways/Neutral"
            htf_info = {"supported": True, "state": htf_regime["state"]}

        # القرار النهائي
        verdict = "SKIP"
        total_score = 0
        reasons = []
        
        if buy_score >= 60 and htf_supported_buy: # تخفيف الشرط من 70 إلى 60
            verdict = "BUY"
            total_score = buy_score
            reasons = buy_reasons
        elif sell_score >= 60 and htf_supported_sell:
            verdict = "SELL"
            total_score = sell_score
            reasons = sell_reasons

        return {
            "total_score": total_score,
            "verdict": verdict,
            "reasons": reasons,
            "regime_data": regime,
            "indicators_data": inds,
            "smc_data": smc,
            "htf_data": htf_info,
            "confidence": total_score,
            "probability": total_score,
            "score_data": {"total": total_score}, # توافق مع AIEngine
            "quality_data": {"total": total_score}, # توافق مع AIEngine
            "validation_data": {"conditions": []}, # توافق مع AIEngine
            "rejection_data": {"reasons": []} # توافق مع AIEngine
        }

    def get_trade_params(self, df: pd.DataFrame, side="BUY"):
        price = df['close'].iloc[-1]
        atr = AverageTrueRange(df['high'], df['low'], df['close']).average_true_range().iloc[-1]
        
        if side == "BUY":
            local_low = df['low'].iloc[-20:].min()
            sl = min(local_low, price - (atr * 1.5))
            if (price - sl) / price > 0.08: sl = price * 0.92 # زيادة حد الوقف إلى 8%
            risk = price - sl
            tp = price + (risk * 1.8) # تقليل الـ RR المطلوب قليلاً لزيادة معدل التنفيذ
        else:
            local_high = df['high'].iloc[-20:].max()
            sl = max(local_high, price + (atr * 1.5))
            if (sl - price) / price > 0.08: sl = price * 1.08
            risk = sl - price
            tp = price - (risk * 1.8)
            
        risk_pct = round((abs(price - sl) / price) * 100, 2)
        rr = round(abs(tp - price) / abs(price - sl), 2) if abs(price - sl) > 0 else 0
        
        return {
            "entry": price, "sl": round(sl, 8), "tp": round(tp, 8), 
            "atr": atr, "rr": rr, "risk_pct": risk_pct
        }
