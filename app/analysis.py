from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from .config import Settings
from .indicators import atr, detect_swings, ema, momentum_context, relative_volume
from .models import AnalysisSnapshot, Candle, NoTrade, Signal, StructureSnapshot


class AnalysisEngine:
    def __init__(self, settings: Settings):
        self.settings = settings

    def analyze(
        self,
        symbol: str,
        timeframe: str,
        entry_candles: list[Candle],
        structure_candles: list[Candle] | None = None,
        htf_candles: list[Candle] | None = None,
        data_fresh: bool = True,
    ) -> tuple[AnalysisSnapshot, Signal | NoTrade]:
        structure_candles = structure_candles or entry_candles
        htf_candles = htf_candles or structure_candles
        health = self._health(entry_candles, structure_candles, htf_candles, data_fresh)
        structure = self._structure(structure_candles)
        htf_structure = self._structure(htf_candles)
        fvg = self._fvgs(entry_candles, timeframe)
        ifvg = self._ifvgs(entry_candles, fvg, timeframe)
        order_blocks = self._order_blocks(entry_candles, timeframe)
        liquidity = self._liquidity(entry_candles, structure, timeframe)
        volume = relative_volume(entry_candles)
        momentum = momentum_context(entry_candles)
        volatility = {"atr": atr(entry_candles, self.settings.atr_period), "regime": self._volatility_regime(entry_candles)}
        context_zones = self._nearby_zones(entry_candles, fvg + ifvg + order_blocks)
        bullish, bearish, reasons = self._scores(
            htf_structure, structure, liquidity, context_zones, volume, momentum, volatility
        )
        decision: str = "NO TRADE"
        if bullish >= self.settings.min_signal_score and bullish - bearish >= self.settings.min_direction_gap:
            decision = "BUY"
        elif bearish >= self.settings.min_signal_score and bearish - bullish >= self.settings.min_direction_gap:
            decision = "SELL"
        snapshot = AnalysisSnapshot(
            symbol=symbol,
            timeframe=timeframe,
            generated_at=datetime.now(timezone.utc).isoformat(),
            data_health=health,
            htf_trend=htf_structure.trend,
            structure=structure,
            fvg=fvg,
            ifvg=ifvg,
            order_blocks=order_blocks,
            liquidity=liquidity,
            volume=volume,
            momentum=momentum,
            volatility=volatility,
            bullish_score=round(bullish, 2),
            bearish_score=round(bearish, 2),
            decision=decision if health["healthy"] else "NO TRADE",
            reasons=reasons,
        )
        if not health["healthy"]:
            return snapshot, NoTrade(symbol, timeframe, reasons=[health["reason"]], score=max(bullish, bearish))
        if decision == "NO TRADE":
            no_trade_reasons = list(reasons)
            if max(bullish, bearish) < self.settings.min_signal_score:
                no_trade_reasons.append("LOW SCORE")
            elif abs(bullish - bearish) < self.settings.min_direction_gap:
                no_trade_reasons.append("DIRECTION GAP TOO SMALL")
            return snapshot, NoTrade(symbol, timeframe, reasons=list(dict.fromkeys(no_trade_reasons)), score=max(bullish, bearish))
        signal = self._build_signal(
            symbol, timeframe, decision, max(bullish, bearish), entry_candles, structure, liquidity, fvg, ifvg,
            order_blocks, volume, momentum, htf_structure, health, reasons,
        )
        if signal is None:
            snapshot.decision = "NO TRADE"
            snapshot.reasons.append("RR INVALID")
            return snapshot, NoTrade(symbol, timeframe, reasons=["RR INVALID"], score=max(bullish, bearish))
        return snapshot, signal

    def _health(self, entry: list[Candle], structure: list[Candle], htf: list[Candle], fresh: bool) -> dict[str, Any]:
        if not entry or not structure or not htf:
            return {"healthy": False, "reason": "INSUFFICIENT_HISTORY", "fresh": fresh}
        try:
            for candle in entry[-min(50, len(entry)):]:
                candle.validate()
        except ValueError as exc:
            return {"healthy": False, "reason": f"INVALID_CANDLE:{exc}", "fresh": fresh}
        if self.settings.require_closed_candle and not entry[-1].is_closed:
            return {"healthy": False, "reason": "CANDLE_NOT_CLOSED", "fresh": fresh}
        if not fresh:
            return {"healthy": False, "reason": "DATA_UNHEALTHY", "fresh": False}
        return {"healthy": True, "reason": "OK", "fresh": True, "entry_count": len(entry), "structure_count": len(structure), "htf_count": len(htf)}

    def _structure(self, candles: list[Candle]) -> StructureSnapshot:
        highs, lows = detect_swings(candles, self.settings.swing_left, self.settings.swing_right)
        state = "UNKNOWN"
        trend = "NEUTRAL"
        bos = None
        choch = None
        evidence: list[str] = []
        if len(highs) >= 2 and len(lows) >= 2:
            last_highs = highs[-2:]
            last_lows = lows[-2:]
            higher_high = last_highs[-1].price > last_highs[-2].price
            higher_low = last_lows[-1].price > last_lows[-2].price
            lower_high = last_highs[-1].price < last_highs[-2].price
            lower_low = last_lows[-1].price < last_lows[-2].price
            if higher_high and higher_low:
                state, trend = "HH_HL", "BULLISH"
                evidence.append("HH/HL sequence")
            elif lower_high and lower_low:
                state, trend = "LH_LL", "BEARISH"
                evidence.append("LH/LL sequence")
            else:
                state, trend = "MIXED", "RANGING"
                evidence.append("Mixed structural sequence")
        close = candles[-1].close if candles else 0.0
        protected_high = highs[-1].price if highs else None
        protected_low = lows[-1].price if lows else None
        if trend == "BULLISH" and protected_high is not None and close > protected_high:
            bos = "BULLISH"
            evidence.append("Bullish BOS close")
        if trend == "BEARISH" and protected_low is not None and close < protected_low:
            bos = "BEARISH"
            evidence.append("Bearish BOS close")
        if trend == "BULLISH" and protected_low is not None and close < protected_low:
            choch = "BEARISH"
            evidence.append("Bearish CHOCH candidate")
        if trend == "BEARISH" and protected_high is not None and close > protected_high:
            choch = "BULLISH"
            evidence.append("Bullish CHOCH candidate")
        return StructureSnapshot(
            trend=trend, state=state, bos=bos, choch=choch,
            swing_highs=[item.to_dict() for item in highs[-8:]],
            swing_lows=[item.to_dict() for item in lows[-8:]],
            protected_high=protected_high, protected_low=protected_low, evidence=evidence,
        )

    def _fvgs(self, candles: list[Candle], timeframe: str) -> list[dict[str, Any]]:
        zones: list[dict[str, Any]] = []
        for index in range(2, len(candles)):
            first, _, third = candles[index - 2:index + 1]
            if first.high < third.low:
                zones.append({"kind": "FVG", "direction": "BUY", "low": first.high, "high": third.low, "created_at": third.open_time, "timeframe": timeframe, "status": "ACTIVE"})
            elif first.low > third.high:
                zones.append({"kind": "FVG", "direction": "SELL", "low": third.high, "high": first.low, "created_at": third.open_time, "timeframe": timeframe, "status": "ACTIVE"})
        return zones[-20:]

    def _ifvgs(self, candles: list[Candle], fvgs: list[dict[str, Any]], timeframe: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for zone in fvgs:
            later = [c for c in candles if c.open_time > zone["created_at"]]
            if not later:
                continue
            invalidated = any((c.close < zone["low"] if zone["direction"] == "BUY" else c.close > zone["high"]) for c in later)
            if invalidated:
                flipped = "SELL" if zone["direction"] == "BUY" else "BUY"
                result.append({**zone, "kind": "IFVG", "direction": flipped, "status": "ACTIVE", "source_direction": zone["direction"]})
        return result[-20:]

    def _order_blocks(self, candles: list[Candle], timeframe: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        current_atr = atr(candles, self.settings.atr_period)
        if current_atr <= 0:
            return result
        start = max(1, len(candles) - 80)
        for index in range(start, len(candles)):
            candle = candles[index]
            previous = candles[index - 1]
            body = abs(candle.close - candle.open)
            if body < current_atr * 1.2:
                continue
            if candle.close > candle.open and previous.close < previous.open:
                result.append({"kind": "ORDER_BLOCK", "direction": "BUY", "low": previous.low, "high": previous.high, "created_at": candle.open_time, "timeframe": timeframe, "status": "ACTIVE"})
            elif candle.close < candle.open and previous.close > previous.open:
                result.append({"kind": "ORDER_BLOCK", "direction": "SELL", "low": previous.low, "high": previous.high, "created_at": candle.open_time, "timeframe": timeframe, "status": "ACTIVE"})
        return result[-10:]

    def _liquidity(self, candles: list[Candle], structure: StructureSnapshot, timeframe: str) -> list[dict[str, Any]]:
        levels: list[dict[str, Any]] = []
        tolerance = max(atr(candles, self.settings.atr_period) * 0.15, candles[-1].close * 0.0005 if candles else 0)
        highs = [item["price"] for item in structure.swing_highs]
        lows = [item["price"] for item in structure.swing_lows]
        for values, direction, label in ((highs, "SELL", "EQUAL_HIGHS"), (lows, "BUY", "EQUAL_LOWS")):
            for index in range(1, len(values)):
                if abs(values[index] - values[index - 1]) <= tolerance:
                    levels.append({"kind": "LIQUIDITY", "direction": direction, "level": round((values[index] + values[index - 1]) / 2, 8), "label": label, "timeframe": timeframe, "status": "ACTIVE"})
        if candles:
            last = candles[-1]
            for level in levels:
                value = level["level"]
                swept = (last.high > value + tolerance and last.close < value) if level["direction"] == "SELL" else (last.low < value - tolerance and last.close > value)
                if swept:
                    level["status"] = "SWEEP_CONFIRMED"
        return levels[-15:]

    def _nearby_zones(self, candles: list[Candle], zones: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not candles:
            return []
        price = candles[-1].close
        current_atr = atr(candles, self.settings.atr_period)
        radius = max(current_atr * 3.0, price * 0.01)
        nearby = [zone for zone in zones if zone.get("high", 0) >= price - radius and zone.get("low", 0) <= price + radius]
        recent = sorted(nearby, key=lambda zone: zone.get("created_at", 0), reverse=True)
        selected: list[dict[str, Any]] = []
        counts = {"BUY": 0, "SELL": 0}
        for zone in recent:
            direction = zone.get("direction")
            if direction not in counts or counts[direction] >= 2:
                continue
            selected.append(zone)
            counts[direction] += 1
        return selected

    def _volatility_regime(self, candles: list[Candle]) -> str:
        if len(candles) < 20:
            return "UNKNOWN"
        value = atr(candles, self.settings.atr_period) / candles[-1].close if candles[-1].close else 0
        if value < 0.001:
            return "COMPRESSED"
        if value > 0.05:
            return "CHAOTIC"
        return "NORMAL"

    def _scores(self, htf: StructureSnapshot, structure: StructureSnapshot, liquidity: list[dict[str, Any]], context_zones: list[dict[str, Any]], volume: dict[str, Any], momentum: dict[str, Any], volatility: dict[str, Any]) -> tuple[float, float, list[str]]:
        bullish = 0.0
        bearish = 0.0
        reasons: list[str] = []
        if htf.trend == "BULLISH": bullish += 20; reasons.append("HTF bullish structure")
        elif htf.trend == "BEARISH": bearish += 20; reasons.append("HTF bearish structure")
        if structure.trend == "BULLISH": bullish += 20; reasons.append("Bullish market structure")
        elif structure.trend == "BEARISH": bearish += 20; reasons.append("Bearish market structure")
        if structure.bos == "BULLISH": bullish += 5; reasons.append("Bullish BOS confirmed")
        elif structure.bos == "BEARISH": bearish += 5; reasons.append("Bearish BOS confirmed")
        for item in liquidity:
            if item.get("status") == "SWEEP_CONFIRMED":
                if item["direction"] == "BUY": bullish += 15; reasons.append("Liquidity sweep confirmed for BUY")
                else: bearish += 15; reasons.append("Liquidity sweep confirmed for SELL")
        buy_context = sum(item.get("direction") == "BUY" for item in context_zones)
        sell_context = sum(item.get("direction") == "SELL" for item in context_zones)
        bullish += min(buy_context, 2) * 5
        bearish += min(sell_context, 2) * 5
        if buy_context: reasons.append(f"Bullish nearby FVG/IFVG/OB context ({buy_context})")
        if sell_context: reasons.append(f"Bearish nearby FVG/IFVG/OB context ({sell_context})")
        if momentum.get("direction") == "BULLISH": bullish += 10; reasons.append("Positive momentum")
        elif momentum.get("direction") == "BEARISH": bearish += 10; reasons.append("Negative momentum")
        if volume.get("above_average"):
            if momentum.get("direction") == "BULLISH": bullish += 10; reasons.append("Volume above average")
            elif momentum.get("direction") == "BEARISH": bearish += 10; reasons.append("Volume above average")
        if volatility.get("regime") == "NORMAL":
            bullish += 5; bearish += 5
        return min(bullish, 100.0), min(bearish, 100.0), list(dict.fromkeys(reasons))

    def _build_signal(self, symbol: str, timeframe: str, direction: str, score: float, candles: list[Candle], structure: StructureSnapshot, liquidity: list[dict[str, Any]], fvg: list[dict[str, Any]], ifvg: list[dict[str, Any]], obs: list[dict[str, Any]], volume: dict[str, Any], momentum: dict[str, Any], htf: StructureSnapshot, health: dict[str, Any], reasons: list[str]) -> Signal | None:
        entry = candles[-1].close
        current_atr = atr(candles, self.settings.atr_period)
        if current_atr <= 0:
            return None
        recent_low = min(c.low for c in candles[-12:])
        recent_high = max(c.high for c in candles[-12:])
        if direction == "BUY":
            anchor = structure.protected_low if structure.protected_low is not None and structure.protected_low < entry else recent_low
            stop = anchor - current_atr * self.settings.atr_buffer_multiplier
            risk = entry - stop
            if risk <= 0:
                return None
            tp1, tp2 = entry + risk * self.settings.rr_tp1, entry + risk * self.settings.rr_tp2
        else:
            anchor = structure.protected_high if structure.protected_high is not None and structure.protected_high > entry else recent_high
            stop = anchor + current_atr * self.settings.atr_buffer_multiplier
            risk = stop - entry
            if risk <= 0:
                return None
            tp1, tp2 = entry - risk * self.settings.rr_tp1, entry - risk * self.settings.rr_tp2
        if risk <= current_atr * 0.05:
            return None
        signal_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{symbol}:{timeframe}:{candles[-1].open_time}:{self.settings.config_version}:{direction}"))
        return Signal(
            id=signal_id, symbol=symbol, timeframe=timeframe, direction=direction, status="SIGNAL_CONFIRMED",
            score=round(score, 2), entry=round(entry, 8), stop_loss=round(stop, 8), tp1=round(tp1, 8), tp2=round(tp2, 8),
            created_at=datetime.now(timezone.utc).isoformat(), signal_version=self.settings.config_version,
            risk_reward={"tp1": self.settings.rr_tp1, "tp2": self.settings.rr_tp2}, reasons=reasons,
            structure=structure.to_dict(), liquidity={"levels": liquidity}, fvg={"zones": fvg, "ifvg": ifvg},
            order_block={"zones": obs}, volume=volume, momentum=momentum, trend={"htf": htf.to_dict(), "entry": structure.trend},
            data_health=health, metadata={"risk": risk, "entry_open_time": candles[-1].open_time},
        )
