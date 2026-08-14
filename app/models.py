from __future__ import annotations

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
        if self.high < max(self.open, self.close):
            raise ValueError("high_below_open_or_close")
        if self.low > min(self.open, self.close):
            raise ValueError("low_above_open_or_close")
        if self.high < self.low:
            raise ValueError("high_below_low")
        if self.volume < 0:
            raise ValueError("negative_volume")
        if self.close_time < self.open_time:
            raise ValueError("invalid_time_range")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SwingPoint:
    kind: Literal["HIGH", "LOW"]
    index: int
    price: float
    open_time: int
    confirmed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NoTrade:
    symbol: str
    timeframe: str
    decision: str = "NO TRADE"
    reasons: list[str] = field(default_factory=list)
    score: float = 0.0
    generated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
