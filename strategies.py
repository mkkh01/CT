from __future__ import annotations

import logging
import config
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import ADXIndicator, EMAIndicator, MACD
from ta.volatility import AverageTrueRange
from ta.volume import OnBalanceVolumeIndicator

logger = logging.getLogger("CT_System")

@dataclass
class DirectionalCandidate:
    side: str
    score: float
    reasons: List[str]
    smc_confirmations: int
    valid: bool


class InstitutionalStrategies:
    """
    Radically redesigned Institutional Strategies Engine.
    Implements Clean Architecture, Weighted SMC, Dynamic Market Regime, 
    and Continuous Scoring.
    """

    def __init__(self):
        self.thresholds = {
            "adx": 20,
            "volatility_min": 0.3,
            "ema_distance_pct": 7,
            "rsi_buy": (30, 65),
            "rsi_sell": (35, 70),
            "min_candles": 200,
            "rr_min": 1.5,
            "min_score": 80,
            "htf_mode": getattr(config, "HTF_MODE", "SKIP"),
        }

        # Score Engine Weights (Total = 100)
        self.weights = {
            "trend": 20,
            "momentum": 15,
            "volume": 15,
            "volatility": 10,
            "smc": 25,
            "risk_context": 10,
            "htf": 5,
        }

        # SMC Component Weights (Total = 90 + Inducement = 95)
        self.smc_weights = {
            "bos": 20,
            "choch": 20,
            "liquidity_sweep": 15,
            "fvg": 10,
            "order_block": 5,
            "breaker_block": 10,
            "mitigation_block": 5,
            "inducement": 5,
        }

        # Hysteresis state for Market Regime
        self._last_regime = "Sideways/Neutral"

    # ---------------------------
    # First: Market Regime Engine
    # ---------------------------
    def classify_market(self, df: pd.DataFrame) -> dict:
        """
        Classifies the market regime with Hysteresis and EMA Alignment.
        Prevents 'Regime Flapping' by requiring clear threshold crossings.
        """
        if len(df) < self.thresholds["min_candles"]:
            return {
                "state": "Low Data",
                "bias": "NEUTRAL",
                "confidence": 0,
                "values": {},
                "reason": f"Insufficient data ({len(df)} < {self.thresholds['min_candles']})",
                "metrics": {}
            }

        close = df["close"].iloc[-1]
        
        # Calculate EMAs
        ema20 = EMAIndicator(df["close"], window=20).ema_indicator()
        ema50 = EMAIndicator(df["close"], window=50).ema_indicator()
        ema100 = EMAIndicator(df["close"], window=100).ema_indicator()
        ema200 = EMAIndicator(df["close"], window=200).ema_indicator()
        
        e20, e50, e100, e200 = ema20.iloc[-1], ema50.iloc[-1], ema100.iloc[-1], ema200.iloc[-1]
        
        # Slopes (last 5 candles)
        def get_slope(series, period=5):
            return (series.iloc[-1] - series.iloc[-period]) / period if len(series) >= period else 0

        slope50 = get_slope(ema50)
        slope200 = get_slope(ema200)
        
        # Volatility & Trend Indicators
        adx = ADXIndicator(df["high"], df["low"], df["close"]).adx().iloc[-1]
        atr = AverageTrueRange(df["high"], df["low"], df["close"]).average_true_range().iloc[-1]
        atr_pct = (atr / close) * 100 if close else 0
        
        rolling_20 = df["close"].rolling(20)
        volatility_ratio = (rolling_20.std().iloc[-1] / rolling_20.mean().iloc[-1]) * 100 if rolling_20.mean().iloc[-1] else 0

        # EMA Alignment check
        bullish_alignment = e20 > e50 > e100 > e200
        bearish_alignment = e20 < e50 < e100 < e200
        
        # Entanglement check
        ema_values = [e20, e50, e100, e200]
        ema_spread = (max(ema_values) - min(ema_values)) / e200
        is_entangled = ema_spread < 0.008  # 0.8% threshold for entanglement

        # Logic determination
        new_state = "Sideways/Neutral"
        bias = "NEUTRAL"
        reason = "Market is in a range or transitioning."

        if is_entangled or (abs(slope50) < 0.00001 and abs(slope200) < 0.00001):
            new_state = "Sideways/Neutral"
            reason = "EMAs are entangled or slopes are near zero."
        elif bullish_alignment and slope50 > -0.001:
            if adx > self.thresholds["adx"]:
                new_state = "Strong Uptrend"
                bias = "BULLISH"
                reason = "Full bullish alignment with strong ADX and positive slope."
            else:
                new_state = "Weak Uptrend"
                bias = "BULLISH"
                reason = "Bullish alignment but weak ADX."
        elif bearish_alignment and slope50 < 0:
            if adx > self.thresholds["adx"]:
                new_state = "Strong Downtrend"
                bias = "BEARISH"
                reason = "Full bearish alignment with strong ADX and negative slope."
            else:
                new_state = "Weak Downtrend"
                bias = "BEARISH"
                reason = "Bearish alignment but weak ADX."
        elif abs(close - e200) / e200 < 0.015:
            new_state = "Distribution/Accumulation"
            reason = "Price is oscillating around EMA200."

        # Hysteresis: Prevent flapping
        if "Trend" in self._last_regime and "Trend" not in new_state:
            # If moving from Trend to Neutral, check if it's just a minor dip
            if adx > 18 and ((self._last_regime == "Strong Uptrend" and close > e100) or 
                            (self._last_regime == "Strong Downtrend" and close < e100)):
                new_state = self._last_regime
                reason = f"Hysteresis active: Maintaining {new_state}."

        self._last_regime = new_state
        
        # Confidence calculation
        conf = 0
        if "Strong" in new_state: conf = 75 + min(25, adx)
        elif "Weak" in new_state: conf = 50 + min(20, adx)
        else: conf = 30 + min(20, volatility_ratio * 10)

        return {
            "state": new_state,
            "bias": bias,
            "confidence": round(conf, 2),
            "reason": reason,
            "values": {
                "EMA200": round(e200, 4),
                "Slope50": round(slope50, 6),
                "ADX": round(adx, 2),
                "ATR%": round(atr_pct, 4),
                "EMA_Spread": round(ema_spread, 6)
            },
            "metrics": {
                "is_entangled": is_entangled,
                "volatility_ratio": round(volatility_ratio, 4)
            }
        }

    # ---------------------------
    # Third: Smart Money Engine
    # ---------------------------
    def get_smc_data(self, df: pd.DataFrame) -> dict:
        """
        Redesigned SMC Engine with weighted scoring and confirmation logic.
        """
        last_50 = df.iloc[-50:]
        highest_high = last_50["high"].max()
        lowest_low = last_50["low"].min()
        curr_close = df["close"].iloc[-1]
        
        # Structures
        # Check if current close breaks the highest high of the PREVIOUS 50 candles (excluding current)
        prev_highest = df["high"].iloc[-51:-1].max()
        prev_lowest = df["low"].iloc[-51:-1].min()
        bos_bull = curr_close > prev_highest
        bos_bear = curr_close < prev_lowest
        
        # CHOCH (Change of Character)
        choch_bull = False
        choch_bear = False
        if len(df) > 40:
            prev_high = df["high"].iloc[-40:-20].max()
            prev_low = df["low"].iloc[-40:-20].min()
            if curr_close > prev_high and df["close"].iloc[-21] < prev_low:
                choch_bull = True
            elif curr_close < prev_low and df["close"].iloc[-21] > prev_high:
                choch_bear = True

        # Liquidity Sweep
        liq_bull = df["low"].iloc[-1] < prev_lowest and curr_close > prev_lowest
        liq_bear = df["high"].iloc[-1] > prev_highest and curr_close < prev_highest
        
        # FVG
        fvg_bull = df["low"].iloc[-1] > df["high"].iloc[-3] if len(df) > 3 else False
        fvg_bear = df["high"].iloc[-1] < df["low"].iloc[-3] if len(df) > 3 else False
        
        # Order Block (Impulsive move with volume)
        ob_bull = False
        ob_bear = False
        if len(df) > 5:
            if df["close"].iloc[-1] > df["open"].iloc[-1] and df["close"].iloc[-2] < df["open"].iloc[-2] and df["volume"].iloc[-1] > df["volume"].iloc[-2] * 1.2:
                ob_bull = True
            elif df["close"].iloc[-1] < df["open"].iloc[-1] and df["close"].iloc[-2] > df["open"].iloc[-2] and df["volume"].iloc[-1] > df["volume"].iloc[-2] * 1.2:
                ob_bear = True

        # Breaker / Mitigation Block (Simplified)
        breaker_bull = False
        breaker_bear = False
        # Inducement (Simplified: Sweep of recent minor high/low)
        inducement_bull = False
        inducement_bear = False
        if len(df) > 10:
            minor_low = df["low"].iloc[-10:-1].min()
            minor_high = df["high"].iloc[-10:-1].max()
            if df["low"].iloc[-1] < minor_low and curr_close > minor_low:
                inducement_bull = True
            elif df["high"].iloc[-1] > minor_high and curr_close < minor_high:
                inducement_bear = True

        def calculate_side_smc(is_bull: bool):
            score = 0
            found = []
            
            if (is_bull and bos_bull) or (not is_bull and bos_bear):
                score += self.smc_weights["bos"]
                found.append("BOS")
            if (is_bull and choch_bull) or (not is_bull and choch_bear):
                score += self.smc_weights["choch"]
                found.append("CHOCH")
            if (is_bull and liq_bull) or (not is_bull and liq_bear):
                score += self.smc_weights["liquidity_sweep"]
                found.append("Liquidity Sweep")
            if (is_bull and fvg_bull) or (not is_bull and fvg_bear):
                score += self.smc_weights["fvg"]
                found.append("FVG")
            
            if (is_bull and inducement_bull) or (not is_bull and inducement_bear):
                score += self.smc_weights["inducement"]
                found.append("Inducement")

            # OB/Breaker logic: If no BOS/CHOCH, OB is just a zone (reduced points)
            has_structure = any(x in ["BOS", "CHOCH"] for x in found)
            if (is_bull and ob_bull) or (not is_bull and ob_bear):
                val = self.smc_weights["order_block"] if has_structure else 2
                score += val
                found.append("Order Block" if has_structure else "OB Zone")
                
            return score, found

        bull_score, bull_found = calculate_side_smc(True)
        bear_score, bear_found = calculate_side_smc(False)
        
        direction = "BUY" if bull_score > bear_score else ("SELL" if bear_score > bull_score else "NEUTRAL")
        active_score = bull_score if direction == "BUY" else bear_score
        active_found = bull_found if direction == "BUY" else bear_found
        
        # SMC Confidence (Max weight = 100)
        max_possible = sum(self.smc_weights.values())
        confidence = (active_score / max_possible) * 100

        return {
            "direction": direction,
            "strength": active_score,
            "confidence": round(confidence, 2),
            "reasons": active_found,
            "detected_structures": active_found,
            "bullish_score": bull_score,
            "bearish_score": bear_score,
            "details": {
                "has_liq_sweep": liq_bull or liq_bear,
                "has_structure": bos_bull or bos_bear or choch_bull or choch_bear
            }
        }

    # ---------------------------
    # Sixth: Relative Volume
    # ---------------------------
    def get_indicators_data(self, df: pd.DataFrame) -> dict:
        """
        Indicators with Dynamic Relative Volume (Z-Score).
        """
        close = df["close"]
        volume = df["volume"]
        
        rsi = RSIIndicator(close).rsi().iloc[-1]
        macd = MACD(close).macd_diff().iloc[-1]
        atr = AverageTrueRange(df["high"], df["low"], df["close"]).average_true_range().iloc[-1]
        atr_pct = (atr / close.iloc[-1]) * 100 if close.iloc[-1] else 0
        
        # Dynamic Volume (Z-Score over 20 periods)
        vol_mean = volume.rolling(20).mean().iloc[-1]
        vol_std = volume.rolling(20).std().iloc[-1]
        rel_vol = volume.iloc[-1] / vol_mean if vol_mean > 0 else 0
        z_score_vol = (volume.iloc[-1] - vol_mean) / vol_std if vol_std > 0 else 0
        
        # Dynamic Threshold: Base 1.5, adjusted by ATR (higher volatility needs higher volume)
        dynamic_threshold = 1.5 + (0.2 if atr_pct > 1.0 else 0)

        return {
            "RSI": {
                "current": round(rsi, 2),
                "status_buy": self.thresholds["rsi_buy"][0] < rsi < self.thresholds["rsi_buy"][1],
                "status_sell": self.thresholds["rsi_sell"][0] < rsi < self.thresholds["rsi_sell"][1],
            },
            "MACD": {
                "current": round(macd, 6),
                "status_buy": macd > -0.0001,
                "status_sell": macd < 0.0001,
            },
            "Volume": {
                "current": round(rel_vol, 2),
                "z_score": round(z_score_vol, 2),
                "threshold": round(dynamic_threshold, 2),
                "status": rel_vol > dynamic_threshold
            },
            "ATR%": {
                "current": round(atr_pct, 4),
                "status": atr_pct > self.thresholds["volatility_min"]
            }
        }

    # ---------------------------
    # Fourth & Fifth: Scoring & Probability
    # ---------------------------
    def calculate_combined_score(self, df: pd.DataFrame, df_higher: Optional[pd.DataFrame]) -> dict:
        """
        The Core Analysis Engine. Integrates all modules with hard gates and 
        continuous scoring.
        """
        regime = self.classify_market(df)
        inds = self.get_indicators_data(df)
        smc = self.get_smc_data(df)
        
        # HTF Filter (Second Requirement)
        htf_data = {"supported": False, "state": "No HTF Data", "reason": "No HTF Data"}
        if df_higher is not None:
            htf_regime = self.classify_market(df_higher)
            htf_data = {
                "supported": True,
                "state": htf_regime["state"],
                "bias": htf_regime["bias"],
                "reason": htf_regime["reason"]
            }
        
        # Decision Logic
        side = smc["direction"]
        if side == "NEUTRAL":
            side = regime["bias"]
        
        # If still neutral, pick bias from HTF if available
        if side == "NEUTRAL" and htf_data["supported"]:
            side = htf_data["bias"]
            
        # Continuous Scoring Breakdown
        breakdown = {}
        
        # 1. Trend (20)
        trend_score = 0
        if (side == "BUY" and regime["bias"] == "BULLISH") or (side == "SELL" and regime["bias"] == "BEARISH"):
            trend_score = self.weights["trend"] if "Strong" in regime["state"] else self.weights["trend"] * 0.6
        breakdown["Trend"] = {"score": round(trend_score, 1), "max": self.weights["trend"], "reason": regime["reason"]}
        
        # 2. Momentum (15) - RSI & MACD
        mom_score = 0
        if side == "BUY":
            if inds["RSI"]["status_buy"]: mom_score += self.weights["momentum"] * 0.5
            if inds["MACD"]["status_buy"]: mom_score += self.weights["momentum"] * 0.5
        elif side == "SELL":
            if inds["RSI"]["status_sell"]: mom_score += self.weights["momentum"] * 0.5
            if inds["MACD"]["status_sell"]: mom_score += self.weights["momentum"] * 0.5
        breakdown["Momentum"] = {"score": round(mom_score, 1), "max": self.weights["momentum"], "reason": f"RSI: {inds['RSI']['current']}"}
        
        # 3. Volume (15) - Continuous Scoring
        # Instead of 0 or 10, use a continuous curve based on Z-Score or Relative Volume
        vol_ratio = inds["Volume"]["current"] / inds["Volume"]["threshold"]
        vol_score = min(1.0, vol_ratio) * self.weights["volume"]
        # If extremely high volume (Z-Score > 2), give a small bonus
        if inds["Volume"]["z_score"] > 2.0:
            vol_score = min(self.weights["volume"], vol_score * 1.1)
        breakdown["Volume"] = {"score": round(vol_score, 1), "max": self.weights["volume"], "reason": f"Rel Vol: {inds['Volume']['current']} (Z: {inds['Volume']['z_score']})"}
        
        # 4. Volatility (10)
        volat_score = self.weights["volatility"] if inds["ATR%"]["status"] else 0
        breakdown["Volatility"] = {"score": round(volat_score, 1), "max": self.weights["volatility"], "reason": f"ATR%: {inds['ATR%']['current']}"}
        
        # 5. SMC (25) - Weighted
        smc_score = (smc["confidence"] / 100) * self.weights["smc"]
        breakdown["SMC"] = {"score": round(smc_score, 1), "max": self.weights["smc"], "reason": ", ".join(smc["reasons"])}
        
        # 6. HTF (5)
        htf_score = 0
        if htf_data["supported"]:
            htf_aligned = (side == "BUY" and htf_data["bias"] == "BULLISH") or (side == "SELL" and htf_data["bias"] == "BEARISH")
            if htf_aligned:
                htf_score = self.weights["htf"]
        breakdown["HTF"] = {"score": round(htf_score, 1), "max": self.weights["htf"], "reason": htf_data["state"]}
        
        # 7. Risk Context (10)
        risk_score = self.weights["risk_context"]
        if inds["ATR%"]["current"] > 2.0: risk_score *= 0.5 # High risk environment
        breakdown["Risk Context"] = {"score": round(risk_score, 1), "max": self.weights["risk_context"], "reason": "Market risk assessed"}

        total_score = sum(v["score"] for v in breakdown.values())
        
        # Hard Gates & Rejection Reasons (Eighth Requirement)
        rejections = []
        if side == "NEUTRAL": 
            rejections.append("No clear directional bias detected in Regime or SMC.")
        
        if not smc["details"]["has_structure"]: 
            rejections.append("SMC: No BOS or CHOCH detected after last sweep. Zone is unconfirmed.")
        
        if not smc["details"]["has_liq_sweep"]: 
            rejections.append("SMC: No Liquidity Sweep found. Entry lacks institutional confirmation.")
            
        if inds["Volume"]["current"] < 0.8: 
            impact = round((1 - inds["Volume"]["current"]) * 100, 1)
            rejections.append(f"Volume: Relative Volume {inds['Volume']['current']} is {impact}% below average. Low participation.")
        
        # HTF Logic (Second Requirement)
        if htf_data["state"] == "No HTF Data":
            mode = self.thresholds["htf_mode"]
            if mode == "SKIP":
                rejections.append("HTF: Higher Timeframe data missing. Safety SKIP enabled.")
            elif mode == "CONTINUE_LOW_CONF":
                total_score *= 0.7
                rejections.append("HTF: Data missing. Continuing with 30% confidence penalty.")
        elif htf_data["bias"] != side and htf_data["bias"] != "NEUTRAL":
            # If side is same but just different string, ignore
            if not (side in ["BUY", "SELL"] and htf_data["bias"] in ["BULLISH", "BEARISH"] and 
                   ((side == "BUY" and htf_data["bias"] == "BULLISH") or (side == "SELL" and htf_data["bias"] == "BEARISH"))):
                rejections.append(f"HTF: Trend conflict. HTF is {htf_data['bias']} while LTF is {side}.")
        
        # Verdict
        verdict = "SKIP"
        if not rejections and total_score >= self.thresholds["min_score"]:
            verdict = side
            
        # Probability Model (Fifth Requirement)
        # Prob = Math-based independent model
        # Factors: Score (40%), SMC Confidence (30%), Regime (20%), Volatility/Volume (10%)
        p_score = (total_score / 100) * 40
        p_smc = (smc["confidence"] / 100) * 30
        p_regime = (regime["confidence"] / 100) * 20
        p_vol = (min(1.0, inds["Volume"]["current"] / 1.5)) * 10
        
        prob = p_score + p_smc + p_regime + p_vol
        # Probability should not be zero unless data is invalid
        prob = max(5, min(98, prob)) if verdict != "SKIP" else max(2, prob * 0.5)

        return {
            "total_score": int(total_score),
            "verdict": verdict,
            "reasons": rejections if verdict == "SKIP" else smc["reasons"],
            "reason": " | ".join(rejections if verdict == "SKIP" else smc["reasons"]),
            "regime_data": regime,
            "indicators_data": inds,
            "smc_data": smc,
            "htf_data": htf_data,
            "confidence": int(total_score),
            "probability": int(prob),
            "score_data": {"total": int(total_score), "breakdown": breakdown},
            "quality_data": {"total": int(total_score), "breakdown": {k: v["score"] for k, v in breakdown.items()}},
            "rejection_data": {"reasons": rejections},
            "validation_data": {"conditions": []}
        }

    def get_trade_params(self, df: pd.DataFrame, side: str = "BUY") -> dict:
        price = float(df["close"].iloc[-1])
        atr = float(AverageTrueRange(df["high"], df["low"], df["close"]).average_true_range().iloc[-1])

        side = (side or "").upper()
        if side not in {"BUY", "SELL"}:
            return {"entry": price, "sl": price, "tp": price, "risk_pct": 0.0, "rr": 0.0}

        if side == "BUY":
            local_low = float(df["low"].iloc[-20:].min())
            sl = min(local_low, price - (atr * 2.0))
            risk = price - sl
            tp = price + (risk * 2.0)
        else:
            local_high = float(df["high"].iloc[-20:].max())
            sl = max(local_high, price + (atr * 2.0))
            risk = sl - price
            tp = price - (risk * 2.0)

        risk_pct = round((abs(price - sl) / price) * 100, 2) if price else 0.0
        rr = round(abs(tp - price) / abs(price - sl), 2) if price != sl else 0.0

        return {"entry": price, "sl": sl, "tp": tp, "risk_pct": risk_pct, "rr": rr}
