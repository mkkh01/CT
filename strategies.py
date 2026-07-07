import logging
from collections import OrderedDict

import numpy as np
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import ADXIndicator, EMAIndicator, MACD
from ta.volatility import AverageTrueRange, BollingerBands
from ta.volume import OnBalanceVolumeIndicator

logger = logging.getLogger(__name__)


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
            "rr_min": 1.5,
            # Used by the unified decision engine trace
            "max_risk_pct": 2.0,
        }
        self.decision_thresholds = {
            "score": 60,
            "quality": 60,
            "confidence": 60,
            "probability": 60,
            "max_risk_pct": self.thresholds["max_risk_pct"],
            "rr_min": self.thresholds["rr_min"],
        }
        self.weights = {
            "trend": 25,
            "rsi": 15,
            "macd": 10,
            "volume": 15,
            "fvg": 15,
            "bos": 10,
            "liquidity": 10,
        }

    def classify_market(self, df: pd.DataFrame) -> dict:
        """تصنيف السوق مع استخراج القيم الرقمية للتشخيص"""
        if len(df) < self.thresholds["min_candles"]:
            return {
                "state": "Low Data",
                "confidence": 0,
                "values": {},
                "reason": f"Not enough candles (minimum {self.thresholds['min_candles']} required)",
                "others_rejected": "All systems rejected due to insufficient data.",
            }

        close = df["close"].iloc[-1]

        # حساب المتوسطات
        ema20 = EMAIndicator(df["close"], window=20).ema_indicator().iloc[-1]
        ema50 = EMAIndicator(df["close"], window=50).ema_indicator().iloc[-1]
        ema100 = EMAIndicator(df["close"], window=100).ema_indicator().iloc[-1]
        ema200 = EMAIndicator(df["close"], window=200).ema_indicator().iloc[-1]

        # حساب ADX لقوة الترند
        adx_ind = ADXIndicator(df["high"], df["low"], df["close"])
        adx = adx_ind.adx().iloc[-1]

        # حساب الانحراف المعياري والتقلب
        rolling_20 = df["close"].rolling(20)
        std_dev = rolling_20.std().iloc[-1]
        avg_price = rolling_20.mean().iloc[-1]
        volatility_ratio = (std_dev / avg_price) * 100 if avg_price else 0

        atr_ind = AverageTrueRange(df["high"], df["low"], df["close"])
        atr = atr_ind.average_true_range().iloc[-1]
        atr_pct = (atr / close) * 100 if close else 0

        # Slope calculation
        slope = (df["close"].iloc[-1] - df["close"].iloc[-5]) / 5 if len(df) >= 5 else 0

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
            "Distance EMA200": round(abs(close - ema200), 2),
        }

        others_rejected = []

        # Better trend detection
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
            "others_rejected": " | ".join(others_rejected),
        }

    def get_indicators_data(self, df: pd.DataFrame) -> dict:
        """جمع كافة القيم الرقمية للمؤشرات المطلوبة"""
        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]

        rsi = RSIIndicator(close).rsi().iloc[-1]
        macd_ind = MACD(close)
        macd_hist = macd_ind.macd_diff().iloc[-1]
        atr = AverageTrueRange(high, low, close).average_true_range().iloc[-1]
        atr_pct = (atr / close.iloc[-1]) * 100 if close.iloc[-1] else 0
        avg_vol = volume.rolling(20).mean().iloc[-1]
        curr_vol = volume.iloc[-1]
        rel_vol = curr_vol / avg_vol if avg_vol > 0 else 0
        ema200 = EMAIndicator(close, window=200).ema_indicator().iloc[-1]
        dist_ema200 = abs(close.iloc[-1] - ema200) / close.iloc[-1] * 100 if close.iloc[-1] else 0

        return {
            "RSI": {
                "current": round(rsi, 2),
                "required_buy": f"{self.thresholds['rsi_buy'][0]}~{self.thresholds['rsi_buy'][1]}",
                "required_sell": f"{self.thresholds['rsi_sell'][0]}~{self.thresholds['rsi_sell'][1]}",
                "status_buy": self.thresholds["rsi_buy"][0] < rsi < self.thresholds["rsi_buy"][1],
                "status_sell": self.thresholds["rsi_sell"][0] < rsi < self.thresholds["rsi_sell"][1],
            },
            "MACD": {
                "current": round(macd_hist, 6),
                "required": "> -0.0001 (Buy) / < 0.0001 (Sell)",
                "status_buy": macd_hist > -0.0001,
                "status_sell": macd_hist < 0.0001,
            },
            "ATR %": {
                "current": round(atr_pct, 4),
                "required": f"> {self.thresholds['volatility']}",
                "status": atr_pct > self.thresholds["volatility"],
            },
            "Volume": {
                "current": round(rel_vol, 2),
                "required": "> 1.0",
                "status": rel_vol > 1.0,
                "info": f"Curr: {round(curr_vol, 0)} / Avg: {round(avg_vol, 0)}",
            },
            "EMA Distance": {
                "current": round(dist_ema200, 2),
                "required": f"< {self.thresholds['ema_distance_pct']}%",
                "status": dist_ema200 < self.thresholds["ema_distance_pct"],
            },
        }

    def get_smc_data(self, df: pd.DataFrame) -> dict:
        """تحليل مفاهيم الأموال الذكية (SMC) واستخراج القيم"""
        last_50 = df.iloc[-50:]
        highest_high = last_50["high"].max()
        lowest_low = last_50["low"].min()
        curr_close = df["close"].iloc[-1]

        # FVG (Fair Value Gap)
        fvg_bullish = False
        fvg_bearish = False
        if len(df) > 3:
            if df["low"].iloc[-1] > df["high"].iloc[-3]:
                fvg_bullish = True
            elif df["high"].iloc[-1] < df["low"].iloc[-3]:
                fvg_bearish = True

        # BOS (Break of Structure)
        bos_bullish = curr_close > highest_high
        bos_bearish = curr_close < lowest_low

        # Liquidity Sweep
        liq_sweep_bullish = df["low"].iloc[-1] < lowest_low and curr_close > lowest_low
        liq_sweep_bearish = df["high"].iloc[-1] > highest_high and curr_close < highest_high

        # Order Block (Simplified)
        ob_bullish = False
        ob_bearish = False
        if len(df) > 5:
            if df["close"].iloc[-1] > df["open"].iloc[-1] and df["close"].iloc[-2] < df["open"].iloc[-2]:
                ob_bullish = True
            elif df["close"].iloc[-1] < df["open"].iloc[-1] and df["close"].iloc[-2] > df["open"].iloc[-2]:
                ob_bearish = True

        return {
            "BOS": {
                "exists": bos_bullish or bos_bearish,
                "info": "Bullish BOS" if bos_bullish else ("Bearish BOS" if bos_bearish else "None"),
                "confidence": 90 if (bos_bullish or bos_bearish) else 0,
                "bullish": bos_bullish,
                "bearish": bos_bearish,
            },
            "FVG": {
                "exists": fvg_bullish or fvg_bearish,
                "info": "Bullish FVG" if fvg_bullish else ("Bearish FVG" if fvg_bearish else "None"),
                "confidence": 80 if (fvg_bullish or fvg_bearish) else 0,
                "bullish": fvg_bullish,
                "bearish": fvg_bearish,
            },
            "Liquidity": {
                "exists": liq_sweep_bullish or liq_sweep_bearish,
                "info": "Bullish Sweep" if liq_sweep_bullish else ("Bearish Sweep" if liq_sweep_bearish else "None"),
                "confidence": 85 if (liq_sweep_bullish or liq_sweep_bearish) else 0,
                "bullish": liq_sweep_bullish,
                "bearish": liq_sweep_bearish,
            },
            "OrderBlock": {
                "exists": ob_bullish or ob_bearish,
                "info": "Bullish OB" if ob_bullish else ("Bearish OB" if ob_bearish else "None"),
                "confidence": 75 if (ob_bullish or ob_bearish) else 0,
                "bullish": ob_bullish,
                "bearish": ob_bearish,
            },
        }

    def _print_decision_trace(self, checks):
        print("\n========== Decision Engine Trace ==========")
        for check in checks:
            threshold = check.get("threshold", "n/a")
            current = check.get("current", "n/a")
            extra = check.get("extra", "")
            print(
                f"{check['name']:<18} | Current: {current} | Threshold: {threshold} | "
                f"Status: {'PASS' if check['status'] else 'FAIL'}{(' | ' + extra) if extra else ''}"
            )
        print("===========================================\n")

    def calculate_combined_score(self, df: pd.DataFrame, df_higher: pd.DataFrame = None) -> dict:
        regime = self.classify_market(df)
        inds = self.get_indicators_data(df)
        smc = self.get_smc_data(df)

        # Validation Conditions
        validation_conditions = [
            {"name": "Min Candles", "status": len(df) >= self.thresholds["min_candles"]},
            {"name": "Volatility Check", "status": inds["ATR %"]["status"]},
            {"name": "Volume Check", "status": inds["Volume"]["status"]},
            {"name": "EMA Distance Check", "status": inds["EMA Distance"]["status"]},
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
            "reason": f"FVG: {fvg_score}, BOS: {bos_score}, Liq: {liq_score}",
        }

        total_score = sum(v["score"] for v in score_breakdown.values())
        quality_total = total_score
        confidence_total = total_score
        probability_total = total_score

        # HTF Filter
        htf_supported_buy = True
        htf_supported_sell = True
        htf_state = "No HTF Data"
        htf_reason = "No HTF Data"

        if df_higher is not None and len(df_higher) >= self.thresholds["min_candles"]:
            htf_regime = self.classify_market(df_higher)
            htf_state = htf_regime["state"]
            htf_reason = htf_regime["reason"]
            htf_supported_buy = "Uptrend" in htf_regime["state"] or htf_regime["state"] == "Sideways/Neutral"
            htf_supported_sell = "Downtrend" in htf_regime["state"] or htf_regime["state"] == "Sideways/Neutral"

        htf_info = {
            "supported": htf_supported_buy or htf_supported_sell,
            "state": htf_state,
            "reason": htf_reason,
            "conditions": [
                {"name": "HTF Trend Alignment Buy", "status": htf_supported_buy, "value": htf_state},
                {"name": "HTF Trend Alignment Sell", "status": htf_supported_sell, "value": htf_state},
            ],
        }

        # Unified decision trace (same list for reasons and final verdict)
        allowed_regimes = {"Strong Uptrend", "Weak Uptrend", "Strong Downtrend", "Weak Downtrend"}
        regime_allowed = regime["state"] in allowed_regimes
        smc_required = any(component["exists"] for component in smc.values())
        score_ok = total_score >= self.decision_thresholds["score"]
        quality_ok = quality_total >= self.decision_thresholds["quality"]
        confidence_ok = confidence_total >= self.decision_thresholds["confidence"]
        probability_ok = probability_total >= self.decision_thresholds["probability"]

        selected_side = None
        htf_alignment_ok = False
        strategy_valid = False
        rr_ok = False
        risk_ok = False
        trade_params = {
            "entry": df["close"].iloc[-1],
            "sl": df["close"].iloc[-1],
            "tp": df["close"].iloc[-1],
            "atr": 0,
            "rr": 0,
            "risk_pct": 0.0,
        }

        buy_candidate = regime_allowed and htf_supported_buy and inds["RSI"]["status_buy"] and inds["MACD"]["status_buy"]
        sell_candidate = regime_allowed and htf_supported_sell and inds["RSI"]["status_sell"] and inds["MACD"]["status_sell"]

        if score_ok:
            if buy_candidate:
                selected_side = "BUY"
            elif sell_candidate:
                selected_side = "SELL"

        if selected_side in {"BUY", "SELL"}:
            trade_params = self.get_trade_params(df, side=selected_side)
            htf_alignment_ok = htf_supported_buy if selected_side == "BUY" else htf_supported_sell
            strategy_valid = True
            risk_ok = trade_params["risk_pct"] <= self.decision_thresholds["max_risk_pct"]
            rr_ok = trade_params["rr"] >= self.decision_thresholds["rr_min"]

        decision_checks = [
            {
                "name": "score >= threshold",
                "current": total_score,
                "threshold": self.decision_thresholds["score"],
                "status": score_ok,
            },
            {
                "name": "quality >= threshold",
                "current": quality_total,
                "threshold": self.decision_thresholds["quality"],
                "status": quality_ok,
            },
            {
                "name": "confidence >= threshold",
                "current": confidence_total,
                "threshold": self.decision_thresholds["confidence"],
                "status": confidence_ok,
            },
            {
                "name": "probability >= threshold",
                "current": probability_total,
                "threshold": self.decision_thresholds["probability"],
                "status": probability_ok,
            },
            {
                "name": "risk <= max_risk",
                "current": round(trade_params["risk_pct"], 2),
                "threshold": self.decision_thresholds["max_risk_pct"],
                "status": risk_ok,
                "extra": f"side={selected_side or 'N/A'}",
            },
            {
                "name": "htf_alignment",
                "current": htf_state,
                "threshold": "side-specific",
                "status": htf_alignment_ok,
                "extra": f"buy={htf_supported_buy}, sell={htf_supported_sell}",
            },
            {
                "name": "smc_required",
                "current": ", ".join([name for name, comp in ((k, v) for k, v in smc.items()) if comp["exists"]]) or "none",
                "threshold": "any SMC signal",
                "status": smc_required,
                "extra": "OrderBlock included in SMC presence check",
            },
            {
                "name": "regime_allowed",
                "current": regime["state"],
                "threshold": ", ".join(sorted(allowed_regimes)),
                "status": regime_allowed,
            },
            {
                "name": "strategy_valid",
                "current": selected_side or "N/A",
                "threshold": "BUY/SELL candidate",
                "status": strategy_valid,
                "extra": f"buy_candidate={buy_candidate}, sell_candidate={sell_candidate}",
            },
            {
                "name": "rr_ok",
                "current": round(trade_params["rr"], 2),
                "threshold": self.decision_thresholds["rr_min"],
                "status": rr_ok,
                "extra": f"entry={round(trade_params['entry'], 8)}",
            },
        ]

        # Print the condition trace before the final verdict is committed.
        self._print_decision_trace(decision_checks)

        verdict = "SKIP"
        rejection_reasons = []

        # Use the same decision checks for the final verdict and rejection reasons.
        if not all(c["status"] for c in validation_conditions):
            rejection_reasons.append("Failed validation conditions")
            for c in validation_conditions:
                if not c["status"]:
                    rejection_reasons.append(f"Failed: {c['name']}")

        if all(c["status"] for c in validation_conditions):
            if all(c["status"] for c in decision_checks):
                verdict = selected_side
            else:
                for c in decision_checks:
                    if not c["status"]:
                        rejection_reasons.append(
                            f"Failed: {c['name']} (current={c.get('current')}, threshold={c.get('threshold')})"
                        )

        if verdict == "SKIP" and not rejection_reasons:
            if not (buy_candidate or sell_candidate):
                rejection_reasons.append("No trend alignment with HTF")
            else:
                rejection_reasons.append("Indicators don't match trend direction")

        active_reasons = [v["reason"] for v in score_breakdown.values() if v["score"] > 0]
        if not active_reasons:
            active_reasons = ["No positive signals"]

        return {
            "total_score": total_score,
            "verdict": verdict,
            "reasons": active_reasons,
            "reason": " | ".join(active_reasons) if verdict != "SKIP" else " | ".join(rejection_reasons),
            "regime_data": regime,
            "indicators_data": inds,
            "smc_data": smc,
            "htf_data": htf_info,
            "confidence": confidence_total,
            "probability": probability_total,
            "score_data": {"total": total_score, "breakdown": score_breakdown},
            "quality_data": {"total": quality_total, "breakdown": {k: v["score"] for k, v in score_breakdown.items()}},
            "validation_data": {"conditions": validation_conditions},
            "rejection_data": {
                "reasons": rejection_reasons,
                "checks": decision_checks,
                "selected_side": selected_side,
                "trade_params": trade_params,
            },
            "decision_trace": decision_checks,
            "trade_params": trade_params,
        }

    def get_trade_params(self, df: pd.DataFrame, side="BUY"):
        price = df["close"].iloc[-1]
        atr = AverageTrueRange(df["high"], df["low"], df["close"]).average_true_range().iloc[-1]

        if side not in {"BUY", "SELL"}:
            return {
                "entry": price,
                "sl": price,
                "tp": price,
                "atr": atr,
                "rr": 0,
                "risk_pct": 0.0,
            }

        if side == "BUY":
            local_low = df["low"].iloc[-20:].min()
            sl = min(local_low, price - (atr * 1.5))
            if (price - sl) / price > 0.08:
                sl = price * 0.92
            risk = price - sl
            tp = price + (risk * 1.8)
        else:
            local_high = df["high"].iloc[-20:].max()
            sl = max(local_high, price + (atr * 1.5))
            if (sl - price) / price > 0.08:
                sl = price * 1.08
            risk = sl - price
            tp = price - (risk * 1.8)

        risk_pct = round((abs(price - sl) / price) * 100, 2) if price else 0.0
        rr = round(abs(tp - price) / abs(price - sl), 2) if abs(price - sl) > 0 else 0

        return {
            "entry": price,
            "sl": round(sl, 8),
            "tp": round(tp, 8),
            "atr": atr,
            "rr": rr,
            "risk_pct": risk_pct,
        }
