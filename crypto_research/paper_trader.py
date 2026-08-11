from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd
import websockets

from crypto_research.paper_gate import GateDecision
from crypto_research.strategies.candidates import StrategyConfig, add_scores, strategy_entry
from crypto_research.strategies.indicators import add_indicators

LOG = logging.getLogger("paper_trader")


@dataclass
class PaperPosition:
    symbol: str
    entry_timestamp: pd.Timestamp
    entry_price: float
    stop_price: float
    target_price: float
    quantity: float


class PaperTrader:
    """Public-market-data paper monitor. It never calls an order endpoint."""

    def __init__(self, symbols: list[str], strategy: StrategyConfig, gate: GateDecision, max_bars: int = 500):
        if not gate.paper_trading_allowed:
            raise RuntimeError("Paper Trading is blocked by the readiness gate")
        if gate.live_trading_allowed:
            raise RuntimeError("Live execution must remain disabled")
        self.symbols = [s.upper().replace("/", "") for s in symbols]
        self.strategy = strategy
        self.gate = gate
        self.max_bars = max_bars
        self.frames: dict[str, pd.DataFrame] = {}
        self.positions: dict[str, PaperPosition] = {}

    async def run(self) -> None:
        streams = "/".join(f"{symbol.lower()}@kline_1h" for symbol in self.symbols)
        url = f"wss://stream.binance.com:9443/stream?streams={streams}"
        async with websockets.connect(url, ping_interval=30) as ws:
            async for raw in ws:
                message = json.loads(raw)
                data = message.get("data", {})
                if data.get("e") != "kline" or not data.get("k", {}).get("x", False):
                    continue
                await self.on_closed_bar(data["s"].upper(), data["k"])

    async def on_closed_bar(self, symbol: str, kline: dict[str, Any]) -> None:
        row = pd.DataFrame([{
            "timestamp": pd.to_datetime(int(kline["t"]), unit="ms", utc=True),
            "open": float(kline["o"]), "high": float(kline["h"]), "low": float(kline["l"]),
            "close": float(kline["c"]), "volume": float(kline["v"]), "symbol": symbol,
        }])
        frame = pd.concat([self.frames.get(symbol, pd.DataFrame()), row], ignore_index=True).drop_duplicates("timestamp").tail(self.max_bars)
        frame = add_scores(add_indicators(frame))
        self.frames[symbol] = frame
        if len(frame) < 60:
            return
        signal = frame.iloc[-1]
        if symbol not in self.positions and strategy_entry(self.strategy.name, signal, self.strategy.score_threshold):
            raw = float(signal["close"])
            atr = float(signal["atr"])
            stop = raw - self.strategy.atr_stop_multiplier * atr
            target = raw + self.strategy.take_profit_r * (raw - stop)
            self.positions[symbol] = PaperPosition(symbol, signal["timestamp"], raw, stop, target, 0.0)
            LOG.info("PAPER SIGNAL LONG %s entry=%s stop=%s target=%s", symbol, raw, stop, target)
        elif symbol in self.positions:
            position = self.positions[symbol]
            low, high = float(signal["low"]), float(signal["high"])
            if low <= position.stop_price or high >= position.target_price:
                reason = "stop" if low <= position.stop_price else "target"
                LOG.info("PAPER EXIT %s reason=%s price=%s", symbol, reason, position.stop_price if reason == "stop" else position.target_price)
                del self.positions[symbol]
