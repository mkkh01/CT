import pandas as pd
import numpy as np
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange, BollingerBands
from ta.volume import OnBalanceVolumeIndicator

class InstitutionalStrategies:
    def __init__(self):
        # Configuration (can be moved to a config file later)
        self.thresholds = {
            "adx": 20,
            "volatility": 0.3,
            "ema_distance_pct": 7,
            "rsi_buy": (30, 65),
            "rsi_sell": (35, 70),
            "min_candles": 200,
            "rr_min": 1.5
        }
        self.weights = {
            "trend": 25,
            "rsi": 15,
            "macd": 10,
            "volume": 15,
            "fvg": 15,
            "bos": 10,
            "liquidity": 10
        }

    def classify_market(self, df: pd.DataFrame) -> dict:
        """تصنيف السوق مع استخراج القيم الرقمية للتشخيص"""
        if len(df) < self.thresholds["min_candles"]: 
            return {
                "state": "Low Data", 
                "confidence": 0, 
                "values": {}, 
                "reason": f"Not enough candles (minimum {self.thresholds['min_candles']} required)",
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
        
        # Slope calculation
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
        
        # Fix Problem 6: Better trend detection
        # Check if EMAs are stacked (alignment)
        bullish_alignment = close > ema20 > ema50 > ema100 > ema200
        bearish_alignment = close < ema20 < ema50 < ema100 < ema200
        
        if volatility_ratio < self.thresholds["volatility"]:
            state = "Low Volatility Range"
            reason = f"Volatility ratio ({round(volatility_ratio, 2)}%) is below threshold."
            others_rejected.append("Trend: Volatility too low")
        elif bullish_alignment and adx > self.thresholds["adx"]:
            state = "Strong Uptrend"
            reason = "Full EMA alignment (20>50>100>200) and ADX > 20."
        elif bearish_alignment and adx > self.thresholds["adx"]:
            state = "Strong Downtrend"
            reason = "Full EMA alignment (20<50<100<200) and ADX > 20."
        elif close > ema200 and adx > 15:
            state = "Weak Uptrend"
            reason = "Price above EMA200 but incomplete EMA alignment."
        elif close < ema200 and adx > 15:
            state = "Weak Downtrend"
            reason = "Price below EMA200 but incomplete EMA alignment."
        elif abs(close - ema200) / ema200 < 0.02:
            state = "Distribution/Accumulation"
            reason = "Price hovering near EMA200."
        else:
            state = "Sideways/Neutral"
            reason = "No clear trend or volatility breakout."

        return {
            "state": state, 
            "confidence": 85 if "Strong" in state else (60 if "Weak" in state else 40), 
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
        macd_hist = macd_ind.macd_diff().iloc[-1]
        
        atr = AverageTrueRange(high, low, close).average_true_range().iloc[-1]
        atr_pct = (atr / close.iloc[-1]) * 100
        
        avg_vol = volume.rolling(20).mean().iloc[-1]
        curr_vol = volume.iloc[-1]
        rel_vol = curr_vol / avg_vol if avg_vol > 0 else 0
        
        ema200 = EMAIndicator(close, window=200).ema_indicator().iloc[-1]
        dist_ema200 = abs(close.iloc[-1] - ema200) / close.iloc[-1] * 100

        # Fix Problem 4: Add 'required' field
        return {
            "RSI": {
                "current": round(rsi, 2),
                "required_buy": f"{self.thresholds['rsi_buy'][0]}~{self.thresholds['rsi_buy'][1]}",
                "required_sell": f"{self.thresholds['rsi_sell'][0]}~{self.thresholds['rsi_sell'][1]}",
                "status_buy": self.thresholds['rsi_buy'][0] < rsi < self.thresholds['rsi_buy'][1],
                "status_sell": self.thresholds['rsi_sell'][0] < rsi < self.thresholds['rsi_sell'][1]
            },
            "MACD": {
                "current": round(macd_hist, 6),
                "required": "> -0.0001 (Buy) / < 0.0001 (Sell)",
                "status_buy": macd_hist > -0.0001,
                "status_sell": macd_hist < 0.0001
            },
            "ATR %": {
                "current": round(atr_pct, 4),
                "required": f"> {self.thresholds['volatility']}",
                "status": atr_pct > self.thresholds['volatility']
            },
            "Volume": {
                "current": round(rel_vol, 2),
                "required": "> 1.0",
                "status": rel_vol > 1.0,
                "info": f"Curr: {round(curr_vol, 0)} / Avg: {round(avg_vol, 0)}"
            },
            "EMA Distance": {
                "current": round(dist_ema200, 2),
                "required": f"< {self.thresholds['ema_distance_pct']}%",
                "status": dist_ema200 < self.thresholds['ema_distance_pct']
            }
        }

    def get_smc_data(self, df: pd.DataFrame) -> dict:
        """تحليل مفاهيم الأموال الذكية (SMC) واستخراج القيم"""
        # Fix Problem 5: Better SMC detection
        last_50 = df.iloc[-50:]
        highest_high = last_50['high'].max()
        lowest_low = last_50['low'].min()
        curr_close = df['close'].iloc[-1]
        curr_high = df['high'].iloc[-1]
        curr_low = df['low'].iloc[-1]
        
        # FVG (Fair Value Gap)
        fvg_bullish = False
        fvg_bearish = False
        if len(df) > 3:
            # Bullish FVG: Low of candle 1 > High of candle 3
            if df['low'].iloc[-1] > df['high'].iloc[-3]:
                fvg_bullish = True
            # Bearish FVG: High of candle 1 < Low of candle 3
            elif df['high'].iloc[-1] < df['low'].iloc[-3]:
                fvg_bearish = True

        # BOS (Break of Structure)
        bos_bullish = curr_close > highest_high
        bos_bearish = curr_close < lowest_low
        
        # Liquidity Sweep
        liq_sweep_bullish = df['low'].iloc[-1] < lowest_low and curr_close > lowest_low
        liq_sweep_bearish = df['high'].iloc[-1] > highest_high and curr_close < highest_high
        
        # Order Block (Simplified)
        ob_bullish = False
        ob_bearish = False
        # Last down candle before a strong up move
        if len(df) > 5:
            if df['close'].iloc[-1] > df['open'].iloc[-1] and df['close'].iloc[-2] < df['open'].iloc[-2]:
                ob_bullish = True
            elif df['close'].iloc[-1] < df['open'].iloc[-1] and df['close'].iloc[-2] > df['open'].iloc[-2]:
                ob_bearish = True

        return {
            "BOS": {
                "exists": bos_bullish or bos_bearish,
                "info": "Bullish BOS" if bos_bullish else ("Bearish BOS" if bos_bearish else "None"),
                "confidence": 90 if (bos_bullish or bos_bearish) else 0,
                "bullish": bos_bullish, "bearish": bos_bearish
            },
            "FVG": {
                "exists": fvg_bullish or fvg_bearish,
                "info": "Bullish FVG" if fvg_bullish else ("Bearish FVG" if fvg_bearish else "None"),
                "confidence": 80 if (fvg_bullish or fvg_bearish) else 0,
                "bullish": fvg_bullish, "bearish": fvg_bearish
            },
            "Liquidity": {
                "exists": liq_sweep_bullish or liq_sweep_bearish,
                "info": "Bullish Sweep" if liq_sweep_bullish else ("Bearish Sweep" if liq_sweep_bearish else "None"),
                "confidence": 85 if (liq_sweep_bullish or liq_sweep_bearish) else 0,
                "bullish": liq_sweep_bullish, "bearish": liq_sweep_bearish
            },
            "OrderBlock": {
                "exists": ob_bullish or ob_bearish,
                "info": "Bullish OB" if ob_bullish else ("Bearish OB" if ob_bearish else "None"),
                "confidence": 75 if (ob_bullish or ob_bearish) else 0,
                "bullish": ob_bullish, "bearish": ob_bearish
            }
        }

    def calculate_combined_score(self, df: pd.DataFrame, df_higher: pd.DataFrame = None) -> dict:
        regime = self.classify_market(df)
        inds = self.get_indicators_data(df)
        smc = self.get_smc_data(df)
        
        # Fix Problem 1, 7, 8: Detailed breakdown for Score Engine and Validation
        
        # Validation Conditions
        validation_conditions = [
            {"name": "Min Candles", "status": len(df) >= self.thresholds["min_candles"]},
            {"name": "Volatility Check", "status": inds["ATR %"]["status"]},
            {"name": "Volume Check", "status": inds["Volume"]["status"]},
            {"name": "EMA Distance Check", "status": inds["EMA Distance"]["status"]}
        ]
        
        # Score Breakdown
        score_breakdown = {}
        
        # 1. Trend (25 points)
        trend_score = 0
        trend_reason = "No clear trend"
        if regime["state"] == "Strong Uptrend": 
            trend_score = self.weights["trend"]
            trend_reason = "Strong Bullish Trend"
        elif regime["state"] == "Strong Downtrend":
            trend_score = self.weights["trend"]
            trend_reason = "Strong Bearish Trend"
        elif "Weak" in regime["state"]:
            trend_score = self.weights["trend"] * 0.6
            trend_reason = "Weak Trend"
        score_breakdown["Trend"] = {"score": trend_score, "max": self.weights["trend"], "reason": trend_reason}
        
        # 2. RSI (15 points)
        rsi_score = 0
        if inds["RSI"]["status_buy"] or inds["RSI"]["status_sell"]:
            rsi_score = self.weights["rsi"]
        score_breakdown["RSI"] = {"score": rsi_score, "max": self.weights["rsi"], "reason": f"RSI: {inds['RSI']['current']}"}
        
        # 3. MACD (10 points)
        macd_score = 0
        if inds["MACD"]["status_buy"] or inds["MACD"]["status_sell"]:
            macd_score = self.weights["macd"]
        score_breakdown["MACD"] = {"score": macd_score, "max": self.weights["macd"], "reason": f"MACD Hist: {inds['MACD']['current']}"}
        
        # 4. Volume (15 points)
        vol_score = 0
        if inds["Volume"]["status"]:
            vol_score = self.weights["volume"]
        score_breakdown["Volume"] = {"score": vol_score, "max": self.weights["volume"], "reason": f"Rel Vol: {inds['Volume']['current']}"}
        
        # 5. SMC Components (35 points total)
        fvg_score = self.weights["fvg"] if smc["FVG"]["exists"] else 0
        bos_score = self.weights["bos"] if smc["BOS"]["exists"] else 0
        liq_score = self.weights["liquidity"] if smc["Liquidity"]["exists"] else 0
        
        score_breakdown["SMC"] = {
            "score": fvg_score + bos_score + liq_score,
            "max": self.weights["fvg"] + self.weights["bos"] + self.weights["liquidity"],
            "reason": f"FVG: {fvg_score}, BOS: {bos_score}, Liq: {liq_score}"
        }
        
        total_score = sum(v["score"] for v in score_breakdown.values())
        
        # HTF Filter
        htf_supported_buy = True
        htf_supported_sell = True
        htf_info = {"supported": True, "reason": "No HTF Data", "conditions": []}
        
        if df_higher is not None:
            htf_regime = self.classify_market(df_higher)
            htf_supported_buy = "Uptrend" in htf_regime["state"] or htf_regime["state"] == "Sideways/Neutral"
            htf_supported_sell = "Downtrend" in htf_regime["state"] or htf_regime["state"] == "Sideways/Neutral"
            htf_info = {
                "supported": htf_supported_buy or htf_supported_sell, 
                "state": htf_regime["state"],
                "reason": htf_regime["reason"],
                "conditions": [{"name": "HTF Trend Alignment", "status": htf_supported_buy or htf_supported_sell, "value": htf_regime["state"]}]
            }

        # Final Verdict Logic
        verdict = "SKIP"
        rejection_reasons = []
        
        # Check validation first
        if not all(c["status"] for c in validation_conditions):
            rejection_reasons.append("Failed validation conditions")
            for c in validation_conditions:
                if not c["status"]: rejection_reasons.append(f"Failed: {c['name']}")
        
        # Directional scores
        buy_eligible = (regime["state"] in ["Strong Uptrend", "Weak Uptrend"]) and htf_supported_buy
        sell_eligible = (regime["state"] in ["Strong Downtrend", "Weak Downtrend"]) and htf_supported_sell
        
        if total_score >= 60:
            if buy_eligible and inds["RSI"]["status_buy"] and inds["MACD"]["status_buy"]:
                verdict = "BUY"
            elif sell_eligible and inds["RSI"]["status_sell"] and inds["MACD"]["status_sell"]:
                verdict = "SELL"
            else:
                if not buy_eligible and not sell_eligible:
                    rejection_reasons.append("No trend alignment with HTF")
                else:
                    rejection_reasons.append("Indicators don't match trend direction")
        else:
            rejection_reasons.append(f"Score {total_score} below threshold 60")

        active_reasons = [v["reason"] for v in score_breakdown.values() if v["score"] > 0]
        if not active_reasons: active_reasons = ["No positive signals"]

        return {
            "total_score": total_score,
            "verdict": verdict,
            "reasons": active_reasons,
            "reason": " | ".join(active_reasons) if verdict != "SKIP" else " | ".join(rejection_reasons),
            "regime_data": regime,
            "indicators_data": inds,
            "smc_data": smc,
            "htf_data": htf_info,
            "confidence": total_score,
            "probability": total_score,
            "score_data": {"total": total_score, "breakdown": score_breakdown},
            "quality_data": {"total": total_score, "breakdown": {k: v["score"] for k, v in score_breakdown.items()}},
            "validation_data": {"conditions": validation_conditions},
            "rejection_data": {"reasons": rejection_reasons}
        }

    def get_trade_params(self, df: pd.DataFrame, side="BUY"):
        price = df['close'].iloc[-1]
        atr = AverageTrueRange(df['high'], df['low'], df['close']).average_true_range().iloc[-1]
        
        if side == "BUY":
            local_low = df['low'].iloc[-20:].min()
            sl = min(local_low, price - (atr * 1.5))
            if (price - sl) / price > 0.08: sl = price * 0.92
            risk = price - sl
            tp = price + (risk * 1.8)
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
