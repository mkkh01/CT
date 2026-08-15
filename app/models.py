from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

Direction = Literal["BUY", "SELL"]
SignalDecision = Literal["BUY", "SELL", "NO TRADE"]
SignalStatus = Literal[
    "SETUP_DETECTED", "WAITING_CONFIRMATION", "SIGNAL_CONFIRMED", "ENTRY_PENDING",
    "ACTIVE", "TP1_HIT", "TP2_HIT", "SL_HIT", "INVALIDATED", "EXPIRED", "CANCELLED",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Candle:
    symbol: str
    timeframe: str
    open_time: int
    close_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_closed: bool = True
    source: str = "binance"
    received_at: str = field(default_factory=utc_now)

    def validate(self) -> None:
        for name in ("open", "high", "low", "close", "volume"):
            if not math.isfinite(getattr(self, name)):
                raise ValueError(f"non_finite_{name}")
        if self.high < max(self.open, self.close): raise ValueError("high_below_open_or_close")
        if self.low > min(self.open, self.close): raise ValueError("low_above_open_or_close")
        if self.high < self.low: raise ValueError("high_below_low")
        if self.volume < 0: raise ValueError("negative_volume")
        if self.close_time < self.open_time: raise ValueError("invalid_time_range")

    def to_dict(self) -> dict[str, Any]: return asdict(self)


@dataclass
class SwingPoint:
    kind: Literal["HIGH", "LOW"]
    index: int
    price: float
    open_time: int
    confirmed: bool = True

    def to_dict(self) -> dict[str, Any]: return asdict(self)


@dataclass
class StructureSnapshot:
    trend: str = "NEUTRAL"
    state: str = "UNKNOWN"
    bos: str | None = None
    choch: str | None = None
    swing_highs: list[dict[str, Any]] = field(default_factory=list)
    swing_lows: list[dict[str, Any]] = field(default_factory=list)
    protected_high: float | None = None
    protected_low: float | None = None
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]: return asdict(self)


@dataclass
class Zone:
    kind: Literal["FVG", "IFVG", "ORDER_BLOCK", "LIQUIDITY"]
    direction: Direction
    low: float
    high: float
    created_at: int
    timeframe: str
    status: str = "ACTIVE"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]: return asdict(self)


@dataclass
class AnalysisSnapshot:
    symbol: str
    timeframe: str
    generated_at: str
    data_health: dict[str, Any]
    htf_trend: str
    structure: StructureSnapshot
    fvg: list[dict[str, Any]] = field(default_factory=list)
    ifvg: list[dict[str, Any]] = field(default_factory=list)
    order_blocks: list[dict[str, Any]] = field(default_factory=list)
    liquidity: list[dict[str, Any]] = field(default_factory=list)
    volume: dict[str, Any] = field(default_factory=dict)
    momentum: dict[str, Any] = field(default_factory=dict)
    volatility: dict[str, Any] = field(default_factory=dict)
    bullish_score: float = 0.0
    bearish_score: float = 0.0
    score_breakdown: list[dict[str, Any]] = field(default_factory=list)
    decision: SignalDecision = "NO TRADE"
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["structure"] = self.structure.to_dict()
        return data


@dataclass
class Signal:
    id: str
    symbol: str
    timeframe: str
    direction: Direction
    status: SignalStatus
    score: float
    entry: float
    stop_loss: float
    tp1: float
    tp2: float
    created_at: str
    signal_version: str
    risk_reward: dict[str, float]
    reasons: list[str]
    structure: dict[str, Any]
    liquidity: dict[str, Any]
    fvg: dict[str, Any]
    order_block: dict[str, Any]
    volume: dict[str, Any]
    momentum: dict[str, Any]
    trend: dict[str, Any]
    data_health: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]: return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Signal":
        return cls(
            id=str(data["id"]), symbol=str(data["symbol"]), timeframe=str(data["timeframe"]),
            direction=data["direction"], status=data["status"], score=float(data["score"]),
            entry=float(data["entry"]), stop_loss=float(data["stop_loss"]), tp1=float(data["tp1"]), tp2=float(data["tp2"]),
            created_at=str(data["created_at"]), signal_version=str(data["signal_version"]), risk_reward=dict(data.get("risk_reward") or {}),
            reasons=list(data.get("reasons") or []), structure=dict(data.get("structure") or {}), liquidity=dict(data.get("liquidity") or {}),
            fvg=dict(data.get("fvg") or {}), order_block=dict(data.get("order_block") or {}), volume=dict(data.get("volume") or {}),
            momentum=dict(data.get("momentum") or {}), trend=dict(data.get("trend") or {}), data_health=dict(data.get("data_health") or {}),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class Trade:
    id: str
    signal_id: str
    symbol: str
    timeframe: str
    direction: Direction
    status: str
    score: float
    entry: float
    stop_loss: float
    tp1: float
    tp2: float
    created_at: str
    activated_at: str | None = None
    tp1_hit_at: str | None = None
    exit_at: str | None = None
    exit_price: float | None = None
    close_reason: str | None = None
    last_price: float | None = None
    last_candle_open_time: int | None = None
    reasons: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]: return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Trade":
        return cls(
            id=str(data["id"]), signal_id=str(data.get("signal_id", data["id"])), symbol=str(data["symbol"]), timeframe=str(data["timeframe"]),
            direction=data["direction"], status=str(data["status"]), score=float(data["score"]), entry=float(data["entry"]),
            stop_loss=float(data["stop_loss"]), tp1=float(data["tp1"]), tp2=float(data["tp2"]), created_at=str(data["created_at"]),
            activated_at=data.get("activated_at"), tp1_hit_at=data.get("tp1_hit_at"), exit_at=data.get("exit_at"),
            exit_price=float(data["exit_price"]) if data.get("exit_price") is not None else None, close_reason=data.get("close_reason"),
            last_price=float(data["last_price"]) if data.get("last_price") is not None else None,
            last_candle_open_time=int(data["last_candle_open_time"]) if data.get("last_candle_open_time") is not None else None,
            reasons=list(data.get("reasons") or []), payload=dict(data.get("payload") or {}),
        )


@dataclass
class NoTrade:
    symbol: str
    timeframe: str
    decision: str = "NO TRADE"
    reasons: list[str] = field(default_factory=list)
    score: float = 0.0
    generated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]: return asdict(self)
