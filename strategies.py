from __future__ import annotations

from dataclasses import dataclass
from math import exp
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import ADXIndicator, EMAIndicator, MACD
from ta.volatility import AverageTrueRange
from ta.volume import OnBalanceVolumeIndicator


@dataclass
class DirectionalCandidate:
    side: str
    score: float
    reasons: List[str]
    smc_confirmations: int
    valid: bool


class InstitutionalStrategies:
    """Direction-aware scoring engine with hard gates for SMC, trend alignment,
    and execution risk. The goal is to avoid the failure mode where a mixed score
    produces a trade even when institutional confirmation is missing.
    """

    def __init__(self):
        self.thresholds = {
            "adx": 20,
            "volatility": 0.3,
            "ema_distance_pct": 7,
            "rsi_buy": (30, 65),
            "rsi_sell": (35, 70),
            "min_candles": 200,
            "rr_min": 1.5,
            "volume_min": 1.5,
            "min_score": 85,
            "min_smc_confirmations": 2,
            "min_smc_score": 20,
        }

        # Total budget: 100. Directional scoring will only use the matching side.
        self.weights = {
            "trend": 20,
            "rsi": 10,
            "macd": 10,
            "volume": 10,
            "volatility": 10,
            "fvg": 15,
            "bos": 15,
            "liquidity": 10,
            "order_block": 10,
        }

    # ---------------------------
    # Market regime
    # ---------------------------
    def classify_market(self, df: pd.DataFrame) -> dict:
        """Classify the current regime using EMA stack, ADX and ATR volatility.

        Returns a state + bias that can be used as a hard gate.
        """
        if len(df) < self.thresholds["min_candles"]:
            return {
                "state": "Low Data",
                "bias": "NEUTRAL",
                "confidence": 0,
                "values": {},
                "reason": (
                    f"Not enough candles (minimum {self.thresholds['min_candles']} required)"
                ),
                "others_rejected": "All systems rejected due to insufficient data.",
            }

        close = df["close"].iloc[-1]
        ema20 = EMAIndicator(df["close"], window=20).ema_indicator().iloc[-1]
        ema50 = EMAIndicator(df["close"], window=50).ema_indicator().iloc[-1]
        ema100 = EMAIndicator(df["close"], window=100).ema_indicator().iloc[-1]
        ema200 = EMAIndicator(df["close"], window=200).ema_indicator().iloc[-1]
        adx = ADXIndicator(df["high"], df["low"], df["close"]).adx().iloc[-1]

        rolling_20 = df["close"].rolling(20)
        std_dev = rolling_20.std().iloc[-1]
        avg_price = rolling_20.mean().iloc[-1]
        volatility_ratio = (std_dev / avg_price) * 100 if avg_price else 0

        atr = AverageTrueRange(df["high"], df["low"], df["close"]).average_true_range().iloc[-1]
        atr_pct = (atr / close) * 100 if close else 0

        slope = (df["close"].iloc[-1] - df["close"].iloc[-5]) / 5 if len(df) >= 5 else 0

        values = {
            "EMA20": round(ema20, 6),
            "EMA50": round(ema50, 6),
            "EMA100": round(ema100, 6),
            "EMA200": round(ema200, 6),
            "ADX": round(adx, 2),
            "ATR": round(atr, 8),
            "ATR%": round(atr_pct, 4),
            "Volatility": round(volatility_ratio, 4),
            "Slope": round(slope, 8),
            "Distance EMA200": round(abs(close - ema200), 8),
        }

        others_rejected: List[str] = []
        bullish_alignment = close > ema20 > ema50 > ema100 > ema200
        bearish_alignment = close < ema20 < ema50 < ema100 < ema200

        if volatility_ratio < self.thresholds["volatility"]:
            state = "Low Volatility Range"
            bias = "NEUTRAL"
            reason = f"Volatility ratio ({round(volatility_ratio, 2)}%) is below threshold."
            others_rejected.append("Trend: Volatility too low")
        elif bullish_alignment and adx > self.thresholds["adx"]:
            state = "Strong Uptrend"
            bias = "BULLISH"
            reason = "Full EMA alignment (20>50>100>200) and ADX > threshold."
        elif bearish_alignment and adx > self.thresholds["adx"]:
            state = "Strong Downtrend"
            bias = "BEARISH"
            reason = "Full EMA alignment (20<50<100<200) and ADX > threshold."
        elif close > ema200 and adx > 15:
            state = "Weak Uptrend"
            bias = "BULLISH"
            reason = "Price above EMA200 but incomplete EMA alignment."
        elif close < ema200 and adx > 15:
            state = "Weak Downtrend"
            bias = "BEARISH"
            reason = "Price below EMA200 but incomplete EMA alignment."
        elif abs(close - ema200) / ema200 < 0.02:
            state = "Distribution/Accumulation"
            bias = "NEUTRAL"
            reason = "Price hovering near EMA200."
        else:
            state = "Sideways/Neutral"
            bias = "NEUTRAL"
            reason = "No clear trend or volatility breakout."

        confidence = 85 if "Strong" in state else (60 if "Weak" in state else 40)

        return {
            "state": state,
            "bias": bias,
            "confidence": confidence,
            "values": values,
            "reason": reason,
            "others_rejected": " | ".join(others_rejected),
        }

    # ---------------------------
    # Indicators
    # ---------------------------
    def get_indicators_data(self, df: pd.DataFrame) -> dict:
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
        rel_vol = curr_vol / avg_vol if avg_vol and avg_vol > 0 else 0
        ema200 = EMAIndicator(close, window=200).ema_indicator().iloc[-1]
        dist_ema200 = abs(close.iloc[-1] - ema200) / close.iloc[-1] * 100 if close.iloc[-1] else 0
        obv = OnBalanceVolumeIndicator(close=close, volume=volume).on_balance_volume().iloc[-1]

        return {
            "RSI": {
                "current": round(rsi, 2),
                "required_buy": f"{self.thresholds['rsi_buy'][0]}~{self.thresholds['rsi_buy'][1]}",
                "required_sell": f"{self.thresholds['rsi_sell'][0]}~{self.thresholds['rsi_sell'][1]}",
                "status_buy": self.thresholds["rsi_buy"][0] < rsi < self.thresholds["rsi_buy"][1],
                "status_sell": self.thresholds["rsi_sell"][0] < rsi < self.thresholds["rsi_sell"][1],
            },
            "MACD": {
                "current": round(macd_hist, 8),
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
                "required": f"> {self.thresholds['volume_min']}",
                "status": rel_vol > self.thresholds["volume_min"],
                "info": f"Curr: {round(curr_vol, 0)} / Avg: {round(avg_vol, 0)}",
            },
            "EMA Distance": {
                "current": round(dist_ema200, 2),
                "required": f"< {self.thresholds['ema_distance_pct']}%",
                "status": dist_ema200 < self.thresholds["ema_distance_pct"],
            },
            "OBV": {
                "current": round(obv, 2),
                "required": "directional context only",
                "status": True,
            },
        }

    # ---------------------------
    # Smart Money Concepts
    # ---------------------------
    def get_smc_data(self, df: pd.DataFrame) -> dict:
        """Directional SMC detection.

        Important: Order Block is no longer a passive log-only field. It contributes
        to the directional SMC score and to the hard entry gate.
        """
        last_50 = df.iloc[-50:]
        highest_high = last_50["high"].max()
        lowest_low = last_50["low"].min()
        curr_close = df["close"].iloc[-1]

        fvg_bullish = False
        fvg_bearish = False
        if len(df) > 3:
            if df["low"].iloc[-1] > df["high"].iloc[-3]:
                fvg_bullish = True
            elif df["high"].iloc[-1] < df["low"].iloc[-3]:
                fvg_bearish = True

        bos_bullish = curr_close > highest_high
        bos_bearish = curr_close < lowest_low

        liq_sweep_bullish = df["low"].iloc[-1] < lowest_low and curr_close > lowest_low
        liq_sweep_bearish = df["high"].iloc[-1] > highest_high and curr_close < highest_high

        # Simplified OB heuristic: last candle impulsive close after opposite candle.
        ob_bullish = False
        ob_bearish = False
        if len(df) > 5:
            if df["close"].iloc[-1] > df["open"].iloc[-1] and df["close"].iloc[-2] < df["open"].iloc[-2]:
                ob_bullish = True
            elif df["close"].iloc[-1] < df["open"].iloc[-1] and df["close"].iloc[-2] > df["open"].iloc[-2]:
                ob_bearish = True

        bullish_strength = 0
        bearish_strength = 0

        if fvg_bullish:
            bullish_strength += self.weights["fvg"]
        if bos_bullish:
            bullish_strength += self.weights["bos"]
        if liq_sweep_bullish:
            bullish_strength += self.weights["liquidity"]
        if ob_bullish:
            bullish_strength += self.weights["order_block"]

        if fvg_bearish:
            bearish_strength += self.weights["fvg"]
        if bos_bearish:
            bearish_strength += self.weights["bos"]
        if liq_sweep_bearish:
            bearish_strength += self.weights["liquidity"]
        if ob_bearish:
            bearish_strength += self.weights["order_block"]

        direction = "BUY" if bullish_strength > bearish_strength else ("SELL" if bearish_strength > bullish_strength else "NEUTRAL")
        confirmations = int(bool(fvg_bullish or fvg_bearish)) + int(bool(bos_bullish or bos_bearish)) + int(bool(liq_sweep_bullish or liq_sweep_bearish)) + int(bool(ob_bullish or ob_bearish))

        return {
            "direction": direction,
            "bullish_score": bullish_strength,
            "bearish_score": bearish_strength,
            "confirmations": confirmations,
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

    # ---------------------------
    # Helpers
    # ---------------------------
    def _conservative_probability(self, score: float, side: str, smc_confirmations: int, validated: bool) -> int:
        """Map score to a conservative estimated probability.

        This is intentionally not 1:1 with score to avoid conflating a heuristic score
        with a real win probability.
        """
        if not validated:
            return 0
        base = 0
        if score >= 90:
            base = 78
        elif score >= 80:
            base = 62
        elif score >= 70:
            base = 54
        elif score >= 60:
            base = 45
        else:
            base = 32

        bonus = min(12, smc_confirmations * 4)
        if side in {"BUY", "SELL"}:
            bonus += 3
        return int(min(95, base + bonus))

    def _score_direction(self, regime: dict, inds: dict, smc: dict, side: str) -> DirectionalCandidate:
        reasons: List[str] = []
        score = 0.0

        trend_state = regime["state"]
        trend_ok = False
        if side == "BUY":
            trend_ok = trend_state in {"Strong Uptrend", "Weak Uptrend"}
            if trend_state == "Strong Uptrend":
                score += self.weights["trend"]
                reasons.append("Strong bullish trend")
            elif trend_state == "Weak Uptrend":
                score += self.weights["trend"] * 0.6
                reasons.append("Weak bullish trend")
        elif side == "SELL":
            trend_ok = trend_state in {"Strong Downtrend", "Weak Downtrend"}
            if trend_state == "Strong Downtrend":
                score += self.weights["trend"]
                reasons.append("Strong bearish trend")
            elif trend_state == "Weak Downtrend":
                score += self.weights["trend"] * 0.6
                reasons.append("Weak bearish trend")

        rsi_ok = inds["RSI"][f"status_{'buy' if side == 'BUY' else 'sell'}"]
        if rsi_ok:
            score += self.weights["rsi"]
            reasons.append(f"RSI: {inds['RSI']['current']}")

        macd_ok = inds["MACD"][f"status_{'buy' if side == 'BUY' else 'sell'}"]
        if macd_ok:
            score += self.weights["macd"]
            reasons.append(f"MACD Hist: {inds['MACD']['current']}")

        if inds["Volume"]["status"]:
            score += self.weights["volume"]
            reasons.append(f"Rel Vol: {inds['Volume']['current']}")

        if inds["ATR %"]["status"]:
            score += self.weights["volatility"]
            reasons.append(f"ATR %: {inds['ATR %']['current']}")

        # Directional SMC scoring: require confirmations beyond OB-only setups.
        smc_score = 0
        if side == "BUY":
            if smc["FVG"]["bullish"]:
                smc_score += self.weights["fvg"]
            if smc["BOS"]["bullish"]:
                smc_score += self.weights["bos"]
            if smc["Liquidity"]["bullish"]:
                smc_score += self.weights["liquidity"]
            if smc["OrderBlock"]["bullish"]:
                smc_score += self.weights["order_block"]
        else:
            if smc["FVG"]["bearish"]:
                smc_score += self.weights["fvg"]
            if smc["BOS"]["bearish"]:
                smc_score += self.weights["bos"]
            if smc["Liquidity"]["bearish"]:
                smc_score += self.weights["liquidity"]
            if smc["OrderBlock"]["bearish"]:
                smc_score += self.weights["order_block"]

        if smc_score > 0:
            score += smc_score
            reasons.append(
                f"SMC: {smc_score} (dir={side}, FVG={smc['FVG']['info']}, BOS={smc['BOS']['info']}, Liq={smc['Liquidity']['info']}, OB={smc['OrderBlock']['info']})"
            )

        valid = trend_ok and rsi_ok and macd_ok and inds["Volume"]["status"] and inds["ATR %"]["status"]
        return DirectionalCandidate(
            side=side,
            score=score,
            reasons=reasons,
            smc_confirmations=smc["confirmations"],
            valid=valid,
        )

    def _hard_gate(self, regime: dict, htf_data: dict, inds: dict, smc: dict, side: str) -> Tuple[bool, List[str]]:
        reasons: List[str] = []
        ok = True

        if regime["state"] == "Low Data":
            return False, ["Insufficient candles"]

        if not inds["ATR %"]["status"]:
            ok = False
            reasons.append("Volatility below threshold")

        if not inds["Volume"]["status"]:
            ok = False
            reasons.append("Relative volume below threshold")

        if not inds["EMA Distance"]["status"]:
            ok = False
            reasons.append("Price too far from EMA200")

        if side == "BUY" and regime["bias"] == "BEARISH":
            ok = False
            reasons.append("Trend/regime conflict for BUY")
        if side == "SELL" and regime["bias"] == "BULLISH":
            ok = False
            reasons.append("Trend/regime conflict for SELL")

        htf_supported = htf_data.get("supported", True)
        if not htf_supported:
            ok = False
            reasons.append("HTF does not support this direction")

        side_has_smc = (
            smc["FVG"]["bullish"]
            or smc["FVG"]["bearish"]
            or smc["BOS"]["bullish"]
            or smc["BOS"]["bearish"]
            or smc["Liquidity"]["bullish"]
            or smc["Liquidity"]["bearish"]
            or smc["OrderBlock"]["bullish"]
            or smc["OrderBlock"]["bearish"]
        )
        if not side_has_smc:
            ok = False
            reasons.append("No SMC confirmation")

        directional_smc_confirmations = sum(
            [
                int(smc["FVG"]["bullish"] if side == "BUY" else smc["FVG"]["bearish"]),
                int(smc["BOS"]["bullish"] if side == "BUY" else smc["BOS"]["bearish"]),
                int(smc["Liquidity"]["bullish"] if side == "BUY" else smc["Liquidity"]["bearish"]),
                int(smc["OrderBlock"]["bullish"] if side == "BUY" else smc["OrderBlock"]["bearish"]),
            ]
        )
        if directional_smc_confirmations < self.thresholds["min_smc_confirmations"]:
            ok = False
            reasons.append("Directional SMC confirmation missing")

        return ok, reasons

    # ---------------------------
    # Combined score & verdict
    # ---------------------------
    def calculate_combined_score(self, df: pd.DataFrame, df_higher: pd.DataFrame = None) -> dict:
        regime = self.classify_market(df)
        inds = self.get_indicators_data(df)
        smc = self.get_smc_data(df)

        validation_conditions = [
            {"name": "Min Candles", "status": len(df) >= self.thresholds["min_candles"]},
            {"name": "Volatility Check", "status": inds["ATR %"]["status"]},
            {"name": "Volume Check", "status": inds["Volume"]["status"]},
            {"name": "EMA Distance Check", "status": inds["EMA Distance"]["status"]},
        ]

        if df_higher is not None and len(df_higher) >= self.thresholds["min_candles"]:
            htf_regime = self.classify_market(df_higher)
            htf_supported_buy = htf_regime["bias"] in {"BULLISH", "NEUTRAL"}
            htf_supported_sell = htf_regime["bias"] in {"BEARISH", "NEUTRAL"}
            htf_info = {
                "supported": True,
                "state": htf_regime["state"],
                "bias": htf_regime["bias"],
                "reason": htf_regime["reason"],
                "conditions": [
                    {"name": "HTF BUY Alignment", "status": htf_supported_buy, "value": htf_regime["state"]},
                    {"name": "HTF SELL Alignment", "status": htf_supported_sell, "value": htf_regime["state"]},
                ],
            }
        else:
            htf_supported_buy = True
            htf_supported_sell = True
            htf_info = {
                "supported": True,
                "state": "No HTF Data",
                "bias": "NEUTRAL",
                "reason": "No HTF Data",
                "conditions": [],
            }

        buy_candidate = self._score_direction(regime, inds, smc, "BUY")
        sell_candidate = self._score_direction(regime, inds, smc, "SELL")

        buy_gate, buy_gate_reasons = self._hard_gate(regime, {"supported": htf_supported_buy}, inds, smc, "BUY")
        sell_gate, sell_gate_reasons = self._hard_gate(regime, {"supported": htf_supported_sell}, inds, smc, "SELL")

        score_breakdown = {
            "Trend": {"score": 0, "max": self.weights["trend"], "reason": regime["reason"]},
            "RSI": {"score": 0, "max": self.weights["rsi"], "reason": f"RSI: {inds['RSI']['current']}"},
            "MACD": {"score": 0, "max": self.weights["macd"], "reason": f"MACD Hist: {inds['MACD']['current']}"},
            "Volume": {"score": 0, "max": self.weights["volume"], "reason": f"Rel Vol: {inds['Volume']['current']}"},
            "Volatility": {"score": 0, "max": self.weights["volatility"], "reason": f"ATR %: {inds['ATR %']['current']}"},
            "SMC": {"score": 0, "max": sum(self.weights[k] for k in ["fvg", "bos", "liquidity", "order_block"]), "reason": "Directional SMC gated"},
        }

        # Use the better side only if it is valid and above threshold.
        selected = buy_candidate if buy_candidate.score >= sell_candidate.score else sell_candidate
        selected_gate = buy_gate if selected.side == "BUY" else sell_gate
        selected_gate_reasons = buy_gate_reasons if selected.side == "BUY" else sell_gate_reasons

        # Populate score breakdown with the selected side, so the logs stay readable.
        score_breakdown["Trend"]["score"] = self.weights["trend"] if "Strong" in regime["state"] and selected.side == ("BUY" if regime["bias"] == "BULLISH" else "SELL") else (
            self.weights["trend"] * 0.6 if "Weak" in regime["state"] and selected.side == ("BUY" if regime["bias"] == "BULLISH" else "SELL") else 0
        )
        score_breakdown["RSI"]["score"] = self.weights["rsi"] if inds["RSI"][f"status_{'buy' if selected.side == 'BUY' else 'sell'}"] else 0
        score_breakdown["MACD"]["score"] = self.weights["macd"] if inds["MACD"][f"status_{'buy' if selected.side == 'BUY' else 'sell'}"] else 0
        score_breakdown["Volume"]["score"] = self.weights["volume"] if inds["Volume"]["status"] else 0
        score_breakdown["Volatility"]["score"] = self.weights["volatility"] if inds["ATR %"]["status"] else 0
        score_breakdown["SMC"]["score"] = max(selected.score - score_breakdown["Trend"]["score"] - score_breakdown["RSI"]["score"] - score_breakdown["MACD"]["score"] - score_breakdown["Volume"]["score"] - score_breakdown["Volatility"]["score"], 0)
        score_breakdown["SMC"]["reason"] = (
            f"FVG: {smc['FVG']['info']}, BOS: {smc['BOS']['info']}, Liq: {smc['Liquidity']['info']}, OB: {smc['OrderBlock']['info']}"
        )

        total_score = int(round(sum(v["score"] for v in score_breakdown.values())))

        rejection_reasons: List[str] = []
        if not all(c["status"] for c in validation_conditions):
            for c in validation_conditions:
                if not c["status"]:
                    rejection_reasons.append(f"Failed: {c['name']}")

        if selected.side == "BUY":
            if regime["bias"] == "BEARISH":
                rejection_reasons.append("Trend/regime conflict for BUY")
            if not htf_supported_buy:
                rejection_reasons.append("HTF does not support BUY")
        elif selected.side == "SELL":
            if regime["bias"] == "BULLISH":
                rejection_reasons.append("Trend/regime conflict for SELL")
            if not htf_supported_sell:
                rejection_reasons.append("HTF does not support SELL")

        # Hard reject if SMC does not support the chosen side.
        if selected.side == "BUY":
            side_smc_count = sum(
                [
                    int(smc["FVG"]["bullish"]),
                    int(smc["BOS"]["bullish"]),
                    int(smc["Liquidity"]["bullish"]),
                    int(smc["OrderBlock"]["bullish"]),
                ]
            )
        else:
            side_smc_count = sum(
                [
                    int(smc["FVG"]["bearish"]),
                    int(smc["BOS"]["bearish"]),
                    int(smc["Liquidity"]["bearish"]),
                    int(smc["OrderBlock"]["bearish"]),
                ]
            )

        if side_smc_count < self.thresholds["min_smc_confirmations"]:
            rejection_reasons.append("Directional SMC confirmation missing")

        if selected.score < self.thresholds["min_score"]:
            rejection_reasons.append(f"Score {selected.score} below threshold {self.thresholds['min_score']}")

        rejection_reasons.extend([r for r in selected_gate_reasons if r not in rejection_reasons])

        if selected.side not in {"BUY", "SELL"}:
            rejection_reasons.append("No valid direction selected")

        final_verdict = selected.side if not rejection_reasons and selected.valid and selected_gate and total_score >= self.thresholds["min_score"] else "SKIP"

        active_reasons = selected.reasons if final_verdict != "SKIP" else (rejection_reasons or ["No positive signals"])
        probability = self._conservative_probability(total_score, selected.side, smc["confirmations"], final_verdict != "SKIP")

        return {
            "total_score": total_score,
            "verdict": final_verdict,
            "reasons": active_reasons,
            "reason": " | ".join(active_reasons),
            "regime_data": regime,
            "indicators_data": inds,
            "smc_data": smc,
            "htf_data": htf_info,
            "confidence": total_score,
            "probability": probability,
            "score_data": {"total": total_score, "breakdown": score_breakdown},
            "quality_data": {"total": total_score, "breakdown": {k: v["score"] for k, v in score_breakdown.items()}},
            "validation_data": {"conditions": validation_conditions},
            "rejection_data": {"reasons": rejection_reasons},
            "directional_candidates": {
                "buy": {
                    "score": round(buy_candidate.score, 2),
                    "valid": buy_candidate.valid,
                    "smc_confirmations": buy_candidate.smc_confirmations,
                    "reasons": buy_candidate.reasons,
                    "gate": buy_gate,
                    "gate_reasons": buy_gate_reasons,
                },
                "sell": {
                    "score": round(sell_candidate.score, 2),
                    "valid": sell_candidate.valid,
                    "smc_confirmations": sell_candidate.smc_confirmations,
                    "reasons": sell_candidate.reasons,
                    "gate": sell_gate,
                    "gate_reasons": sell_gate_reasons,
                },
            },
        }

    # ---------------------------
    # Trade parameters
    # ---------------------------
    def get_trade_params(self, df: pd.DataFrame, side: str = "BUY") -> dict:
        price = float(df["close"].iloc[-1])
        atr = float(AverageTrueRange(df["high"], df["low"], df["close"]).average_true_range().iloc[-1])

        side = (side or "").upper()
        if side not in {"BUY", "SELL"}:
            return {"entry": price, "sl": price, "tp": price, "risk_pct": 0.0, "rr": 0.0}

        if side == "BUY":
            local_low = float(df["low"].iloc[-20:].min())
            sl = min(local_low, price - (atr * 1.5))
            if price > 0 and (price - sl) / price > 0.08:
                sl = price * 0.92
            risk = price - sl
            tp = price + (risk * 1.8)
        else:
            local_high = float(df["high"].iloc[-20:].max())
            sl = max(local_high, price + (atr * 1.5))
            if price > 0 and (sl - price) / price > 0.08:
                sl = price * 1.08
            risk = sl - price
            tp = price - (risk * 1.8)

        risk_pct = round((abs(price - sl) / price) * 100, 2) if price else 0.0
        rr = round(abs(tp - price) / abs(price - sl), 2) if price != sl else 0.0

        return {"entry": price, "sl": sl, "tp": tp, "risk_pct": risk_pct, "rr": rr}
