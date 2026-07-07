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
        if volatility_ratio < 0.5:
            state = "Low Volatility Range"
            reason = f"Volatility ratio ({round(volatility_ratio, 2)}%) is below 0.5%, indicating a tight range."
            others_rejected.append("Strong Trend: ADX or EMA alignment not met")
        elif close > ema50 > ema200 and adx > 25:
            state = "Strong Uptrend"
            reason = "Price is above EMA50/200 and ADX > 25, showing strong momentum."
            others_rejected.append("Range: Volatility too high for consolidation")
        elif close < ema50 < ema200 and adx > 25:
            state = "Strong Downtrend"
            reason = "Price is below EMA50/200 and ADX > 25, showing strong downward pressure."
            others_rejected.append("Range: Volatility too high for consolidation")
        elif abs(close - ema200) / ema200 < 0.01:
            state = "Distribution/Accumulation"
            reason = "Price is hovering within 1% of EMA200, suggesting a phase shift."
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
        
        bb = BollingerBands(close)
        atr = AverageTrueRange(high, low, close).average_true_range().iloc[-1]
        obv = OnBalanceVolumeIndicator(close, volume).on_balance_volume().iloc[-1]
        
        avg_vol = volume.rolling(20).mean().iloc[-1]
        curr_vol = volume.iloc[-1]
        rel_vol = curr_vol / avg_vol if avg_vol > 0 else 0
        
        ema200 = EMAIndicator(close, window=200).ema_indicator().iloc[-1]

        # Structure for Stage 4 Logging
        return {
            "RSI": {
                "current": round(rsi, 2),
                "required": "40~70",
                "status": 40 < rsi < 70
            },
            "MACD": {
                "current": f"Hist: {round(macd_hist, 6)}",
                "required": "Positive Hist",
                "status": macd_hist > 0
            },
            "ATR %": {
                "current": round((atr/close.iloc[-1])*100, 4),
                "required": "> 0.5",
                "status": (atr/close.iloc[-1])*100 > 0.5
            },
            "Volume": {
                "current": round(rel_vol, 2),
                "required": "> 1.2",
                "status": rel_vol > 1.2,
                "raw": {
                    "Current": round(curr_vol, 2),
                    "Average": round(avg_vol, 2),
                    "Relative": round(rel_vol, 2)
                }
            },
            "EMA Distance": {
                "current": round(abs(close.iloc[-1] - ema200)/close.iloc[-1]*100, 2),
                "required": "< 5%",
                "status": abs(close.iloc[-1] - ema200)/close.iloc[-1]*100 < 5
            }
        }

    def get_smc_data(self, df: pd.DataFrame) -> dict:
        """تحليل مفاهيم الأموال الذكية (SMC) واستخراج القيم"""
        last_50 = df.iloc[-50:]
        highest_high = last_50['high'].max()
        lowest_low = last_50['low'].min()
        curr_close = df['close'].iloc[-1]
        
        # FVG
        fvg_found = False
        fvg_info = "None"
        if len(df) > 3:
            if df['low'].iloc[-1] > df['high'].iloc[-3]:
                fvg_found = True
                fvg_info = f"Bullish Gap ({round(df['high'].iloc[-3], 2)} - {round(df['low'].iloc[-1], 2)})"
            elif df['high'].iloc[-1] < df['low'].iloc[-3]:
                fvg_found = True
                fvg_info = f"Bearish Gap ({round(df['low'].iloc[-3], 2)} - {round(df['high'].iloc[-1], 2)})"

        # BOS/CHOCH
        bos_detected = curr_close > highest_high * 0.99 or curr_close < lowest_low * 1.01
        
        # Liquidity Sweep
        liq_sweep = df['high'].iloc[-1] > highest_high or df['low'].iloc[-1] < lowest_low

        return {
            "BOS/CHOCH": {"exists": bos_detected, "info": "Potential Breakout" if bos_detected else "None", "confidence": 70 if bos_detected else 0},
            "FVG": {"exists": fvg_found, "info": fvg_info, "confidence": 80 if fvg_found else 0},
            "Liquidity Sweep": {"exists": liq_sweep, "info": "Sweep Detected" if liq_sweep else "None", "confidence": 75 if liq_sweep else 0},
            "Order Block": {"exists": abs(curr_close - lowest_low)/lowest_low < 0.005, "info": "Testing Support OB", "confidence": 65}
        }

    def calculate_combined_score(self, df: pd.DataFrame, df_higher: pd.DataFrame = None) -> dict:
        """نظام التقييم المطور مع دعم الـ Logging الاحترافي"""
        # Phase 1: Data Info (will be handled in AIEngine before calling this)
        
        # Phase 2: Market Regime
        regime = self.classify_market(df)
        
        # Score Breakdown for Phase 7
        score_breakdown = {
            "Trend": {"score": 0, "max": 20, "reason": "No trend alignment"},
            "Momentum": {"score": 0, "max": 15, "reason": "Weak momentum"},
            "SMC": {"score": 0, "max": 25, "reason": "No SMC patterns"},
            "Volume": {"score": 0, "max": 15, "reason": "Low relative volume"},
            "Structure": {"score": 0, "max": 20, "reason": "Neutral structure"},
            "Risk": {"score": 5, "max": 5, "reason": "Default risk pass"}
        }

        rejection_reasons = []
        validation_conditions = []

        # 1. Trend & Regime
        if regime["state"] == "Strong Uptrend":
            score_breakdown["Trend"]["score"] = 20
            score_breakdown["Trend"]["reason"] = "Strong Bullish Alignment"
            validation_conditions.append({"name": "Regime Bullish", "status": True})
        else:
            rejection_reasons.append(f"Market Regime = {regime['state']}")
            validation_conditions.append({"name": "Regime Bullish", "status": False})

        # 2. Indicators (Phase 4 & 6)
        inds = self.get_indicators_data(df)
        if inds["RSI"]["status"]:
            score_breakdown["Momentum"]["score"] += 10
            score_breakdown["Momentum"]["reason"] = "Healthy RSI"
            validation_conditions.append({"name": "RSI Healthy", "status": True})
        else:
            rejection_reasons.append(f"RSI = {inds['RSI']['current']} (Required 40~70)")
            validation_conditions.append({"name": "RSI Healthy", "status": False})

        if inds["Volume"]["status"]:
            score_breakdown["Volume"]["score"] = 15
            score_breakdown["Volume"]["reason"] = "High Relative Volume"
            validation_conditions.append({"name": "Volume Confirmation", "status": True})
        else:
            rejection_reasons.append(f"Relative Volume = {inds['Volume']['current']} < 1.2")
            validation_conditions.append({"name": "Volume Confirmation", "status": False})

        # 3. SMC (Phase 5 & 6)
        smc = self.get_smc_data(df)
        if smc["FVG"]["exists"]:
            score_breakdown["SMC"]["score"] += 15
            score_breakdown["SMC"]["reason"] = "FVG Detected"
            validation_conditions.append({"name": "SMC FVG", "status": True})
        else:
            rejection_reasons.append("No FVG Found")
            validation_conditions.append({"name": "SMC FVG", "status": False})

        if smc["BOS/CHOCH"]["exists"]:
            score_breakdown["Structure"]["score"] = 20
            score_breakdown["Structure"]["reason"] = "Market Structure Shift"
            validation_conditions.append({"name": "Structure BOS", "status": True})
        else:
            rejection_reasons.append("No BOS/CHOCH Detected")
            validation_conditions.append({"name": "Structure BOS", "status": False})

        # 4. HTF (Phase 3)
        htf_info = {"supported": False, "reason": "No HTF Data", "conditions": []}
        if df_higher is not None:
            htf_regime = self.classify_market(df_higher)
            htf_bullish = "Uptrend" in htf_regime["state"]
            htf_info["supported"] = htf_bullish
            htf_info["reason"] = "HTF Trend is Bullish" if htf_bullish else f"HTF Trend is {htf_regime['state']}"
            htf_info["conditions"] = [
                {"name": "HTF Trend Bullish", "value": htf_regime["state"], "status": htf_bullish},
                {"name": "HTF ADX > 20", "value": htf_regime["values"].get("ADX", 0), "status": htf_regime["values"].get("ADX", 0) > 20}
            ]
            if htf_bullish:
                score_breakdown["Trend"]["score"] += 0 # Already maxed or handled
            else:
                rejection_reasons.append(f"HTF Trend = {htf_regime['state']}")

        # Calculate Total
        total_score = sum(d["score"] for d in score_breakdown.values())
        
        # Quality Phase 9
        quality_breakdown = {
            "Data Quality": 20,
            "Indicator Quality": 20 if inds["Volume"]["status"] else 10,
            "Trend Confidence": 20 if "Strong" in regime["state"] else 10,
            "SMC Confidence": 20 if smc["FVG"]["exists"] else 5,
            "Liquidity Quality": 20 if smc["Liquidity Sweep"]["exists"] else 10
        }
        total_quality = sum(quality_breakdown.values())

        # Decision Phase 10
        verdict = "BUY" if total_score >= 70 and total_quality >= 60 and htf_info["supported"] else "SKIP"

        return {
            "total_score": total_score,
            "score_data": {"total": total_score, "breakdown": score_breakdown},
            "quality_data": {"total": total_quality, "breakdown": quality_breakdown},
            "reasons": [score_breakdown[k]["reason"] for k in score_breakdown if score_breakdown[k]["score"] > 0],
            "rejection_data": {"reasons": rejection_reasons},
            "regime_data": regime,
            "indicators_data": inds,
            "smc_data": smc,
            "htf_data": htf_info,
            "validation_data": {"conditions": validation_conditions},
            "verdict": verdict,
            "confidence": total_quality,
            "probability": total_score
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
        
        risk_pct = round((abs(price - sl) / price) * 100, 2)
        rr = round((tp - price) / (price - sl), 2) if (price - sl) > 0 else 0
        
        return {
            "entry": price, "sl": round(sl, 8), "tp": round(tp, 8), 
            "atr": atr, "rr": rr, "risk_pct": risk_pct
        }
