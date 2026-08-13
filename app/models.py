from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


@dataclass
class Signal:
    symbol: str
    timeframe: str
    generated_at: datetime
    candle_open_time: int
    entry_price: float
    stop_loss: float
    take_profit: float
    reason: str
    risk_reward: float
    side: str = "BUY"
    status: str = "NEW"
    id: Optional[str] = None
    ifvg_id: Optional[str] = None
    strategy_version: str = "ifvg_v1"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["generated_at"] = iso(self.generated_at)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Signal":
        generated_at = data.get("generated_at")
        if isinstance(generated_at, str):
            generated_at = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        if not isinstance(generated_at, datetime):
            generated_at = utc_now()
        return cls(
            symbol=str(data["symbol"]).upper(),
            timeframe=str(data.get("timeframe", "15m")),
            generated_at=generated_at,
            candle_open_time=int(data["candle_open_time"]),
            entry_price=float(data["entry_price"]),
            stop_loss=float(data["stop_loss"]),
            take_profit=float(data["take_profit"]),
            reason=str(data.get("reason", "IFVG")),
            risk_reward=float(data.get("risk_reward", 0.0)),
            side=str(data.get("side", "BUY")).upper(),
            status=str(data.get("status", "NEW")),
            id=data.get("id"),
            ifvg_id=data.get("ifvg_id"),
            strategy_version=str(data.get("strategy_version", "ifvg_v1")),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class VirtualPosition:
    id: str
    symbol: str
    capital_allocated: float
    entry_price: float
    stop_loss: float
    take_profit: float
    quantity: float
    opened_at: datetime
    signal_id: Optional[str] = None
    side: str = "BUY"
    status: str = "OPEN"
    exit_price: Optional[float] = None
    closed_at: Optional[datetime] = None
    realized_pnl: Optional[float] = None
    close_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["opened_at"] = iso(self.opened_at)
        data["closed_at"] = iso(self.closed_at)
        return data


@dataclass
class RuntimeSnapshot:
    status: str
    last_price_by_symbol: Dict[str, float] = field(default_factory=dict)
    last_event_at: Optional[datetime] = None
    open_positions: list[Dict[str, Any]] = field(default_factory=list)
    realized_pnl_today: float = 0.0
    daily_loss_limit_hit: bool = False
    websocket_connected: bool = False
    last_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["last_event_at"] = iso(self.last_event_at)
        return data
