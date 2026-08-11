from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    fee_bps: float = 10.0
    slippage_bps: float = 2.0
    spread_bps: float = 2.0

    @property
    def fee_rate(self) -> float:
        return self.fee_bps / 10_000.0

    @property
    def execution_rate(self) -> float:
        return (self.slippage_bps + self.spread_bps / 2.0) / 10_000.0

    def buy_price(self, raw_price: float) -> float:
        return raw_price * (1.0 + self.execution_rate)

    def sell_price(self, raw_price: float) -> float:
        return raw_price * (1.0 - self.execution_rate)

    def fee(self, notional: float) -> float:
        return abs(notional) * self.fee_rate

    def to_dict(self) -> dict[str, float]:
        return {"fee_bps": self.fee_bps, "slippage_bps": self.slippage_bps, "spread_bps": self.spread_bps}
