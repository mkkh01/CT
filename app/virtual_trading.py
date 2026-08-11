from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from .config import Settings
from .models import Signal, VirtualPosition

logger = logging.getLogger(__name__)


class VirtualTradingEngine:
    """Simulates entries and exits from live public market data only.

    No Binance API key is accepted by this class and no exchange order is ever
    submitted. Each configured symbol may use its full configured capital.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.selected_symbols = set(settings.selected_symbols)
        self.capital_by_symbol: dict[str, float] = {
            symbol: settings.initial_capital_usdt for symbol in settings.selected_symbols if settings.initial_capital_usdt > 0
        }
        self.positions: dict[str, VirtualPosition] = {}
        self.last_prices: dict[str, float] = {}
        self.closed_trades: list[VirtualPosition] = []
        self.realized_pnl_today = 0.0
        self._loss_day = self._today_key()
        self.daily_loss_limit_hit = False
        self.last_signal_at: dict[str, int] = {}

    @staticmethod
    def _today_key() -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def _roll_day(self) -> None:
        today = self._today_key()
        if today != self._loss_day:
            self._loss_day = today
            self.realized_pnl_today = 0.0
            self.daily_loss_limit_hit = False

    def add_symbol(self, symbol: str) -> None:
        self.selected_symbols.add(symbol.upper())

    def remove_symbol(self, symbol: str) -> bool:
        symbol = symbol.upper()
        if any(position.symbol == symbol for position in self.positions.values()):
            return False
        self.selected_symbols.discard(symbol)
        self.capital_by_symbol.pop(symbol, None)
        return True

    def set_capital(self, symbol: str, amount: float) -> None:
        if amount <= 0:
            raise ValueError("capital must be greater than zero")
        self.capital_by_symbol[symbol.upper()] = float(amount)
        self.selected_symbols.add(symbol.upper())

    def total_capital(self) -> float:
        return sum(self.capital_by_symbol.values())

    def daily_loss_limit_amount(self) -> float:
        return self.total_capital() * self.settings.daily_loss_limit_pct

    def can_open(self, symbol: str) -> tuple[bool, str]:
        self._roll_day()
        symbol = symbol.upper()
        if symbol not in self.selected_symbols:
            return False, "symbol_not_selected"
        if symbol not in self.capital_by_symbol or self.capital_by_symbol[symbol] <= 0:
            return False, "capital_not_configured"
        if len(self.positions) >= self.settings.max_concurrent_positions:
            return False, "max_concurrent_positions"
        if any(position.symbol == symbol for position in self.positions.values()):
            return False, "symbol_position_already_open"
        if self.daily_loss_limit_hit:
            return False, "daily_loss_limit_hit"
        return True, "ok"

    def open_from_signal(self, signal: Signal) -> tuple[Optional[VirtualPosition], str]:
        allowed, reason = self.can_open(signal.symbol)
        if not allowed:
            logger.info("signal_skipped symbol=%s reason=%s", signal.symbol, reason)
            return None, reason

        capital = self.capital_by_symbol[signal.symbol]
        quantity = capital / signal.entry_price
        position = VirtualPosition(
            id=str(uuid.uuid4()),
            symbol=signal.symbol,
            capital_allocated=capital,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            quantity=quantity,
            opened_at=signal.generated_at,
            signal_id=signal.id,
        )
        self.positions[position.id] = position
        self.last_signal_at[signal.symbol] = signal.candle_open_time
        logger.info(
            "virtual_position_opened symbol=%s entry=%.8f stop=%.8f target=%.8f capital=%.2f",
            signal.symbol,
            signal.entry_price,
            signal.stop_loss,
            signal.take_profit,
            capital,
        )
        return position, "opened"

    def on_price(self, symbol: str, price: float) -> list[VirtualPosition]:
        self._roll_day()
        symbol = symbol.upper()
        price = float(price)
        self.last_prices[symbol] = price
        closed = []
        for position in list(self.positions.values()):
            if position.symbol != symbol:
                continue
            if price <= position.stop_loss:
                closed.append(self.close(position.id, price, "STOP_LOSS"))
            elif price >= position.take_profit:
                closed.append(self.close(position.id, price, "TAKE_PROFIT"))
        return [position for position in closed if position is not None]

    def close(self, position_id: str, exit_price: float, reason: str) -> Optional[VirtualPosition]:
        position = self.positions.pop(position_id, None)
        if not position:
            return None
        position.status = "CLOSED"
        position.exit_price = float(exit_price)
        position.closed_at = datetime.now(timezone.utc)
        position.realized_pnl = (position.exit_price - position.entry_price) * position.quantity
        position.close_reason = reason
        self.closed_trades.append(position)
        self.realized_pnl_today += position.realized_pnl
        if self.realized_pnl_today <= -self.daily_loss_limit_amount():
            self.daily_loss_limit_hit = True
        logger.info(
            "virtual_position_closed symbol=%s reason=%s exit=%.8f pnl=%.8f daily_pnl=%.8f",
            position.symbol,
            reason,
            position.exit_price,
            position.realized_pnl,
            self.realized_pnl_today,
        )
        return position

    def position_for_symbol(self, symbol: str) -> Optional[VirtualPosition]:
        return next((p for p in self.positions.values() if p.symbol == symbol.upper()), None)

    def snapshot(self) -> dict[str, Any]:
        self._roll_day()
        return {
            "selected_symbols": sorted(self.selected_symbols),
            "capital_by_symbol": self.capital_by_symbol,
            "total_capital": self.total_capital(),
            "max_concurrent_positions": self.settings.max_concurrent_positions,
            "daily_loss_limit_pct": self.settings.daily_loss_limit_pct,
            "daily_loss_limit_amount": self.daily_loss_limit_amount(),
            "realized_pnl_today": self.realized_pnl_today,
            "daily_loss_limit_hit": self.daily_loss_limit_hit,
            "open_positions": [position.to_dict() for position in self.positions.values()],
            "last_prices": self.last_prices,
        }
