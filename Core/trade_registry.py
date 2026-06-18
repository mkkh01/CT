import uuid
import logging
import asyncio
from datetime import datetime
from typing import Dict, Set, Optional
from enum import Enum

logger = logging.getLogger(__name__)

class TradeStatus(Enum):
    OPEN = "OPEN"
    WON = "WON"
    LOST = "LOST"
    CLOSED = "CLOSED"
    PENDING_CLOSE = "PENDING_CLOSE"

class TradeRegistry:
    """سجل مركزي لجميع الصفقات مع Idempotency Check"""
    
    def __init__(self):
        self.trades: Dict[str, dict] = {}  # trade_id -> trade_data
        self.closed_trades: Set[str] = set()  # trade_ids التي تم إغلاقها
        self.closing_lock: Dict[str, asyncio.Lock] = {}  # قفل لكل صفقة
        self.master_lock = asyncio.Lock()
        self.processed_events: Set[str] = set()  # منع معالجة نفس الحدث مرتين
        
    async def create_trade(self, symbol: str, trade_type: str, entry_price: float, 
                          stop_loss: float, take_profit: float, amount: float,
                          source: str = "LIVE") -> str:
        """إنشاء صفقة جديدة مع trade_id فريد"""
        trade_id = f"{symbol}_{source}_{uuid.uuid4().hex[:8]}"
        
        async with self.master_lock:
            self.trades[trade_id] = {
                "trade_id": trade_id,
                "symbol": symbol,
                "type": trade_type,
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "amount": amount,
                "source": source,
                "status": TradeStatus.OPEN.value,
                "created_at": datetime.utcnow().isoformat(),
                "closed_at": None,
                "exit_price": None,
                "exit_reason": None,
                "pnl": 0.0,
                "close_count": 0,  # عدد محاولات الإغلاق
                "closing_worker": None,  # أي worker أغلق الصفقة
            }
            self.closing_lock[trade_id] = asyncio.Lock()
            
            logger.info(f"✅ [TRADE REGISTRY] تم إنشاء صفقة جديدة: {trade_id} | {symbol} @ {entry_price}")
        
        return trade_id
    
    async def can_close_trade(self, trade_id: str) -> bool:
        """التحقق من إمكانية إغلاق الصفقة (Idempotency Check)"""
        async with self.master_lock:
            if trade_id not in self.trades:
                logger.warning(f"⚠️ [TRADE REGISTRY] محاولة إغلاق صفقة غير موجودة: {trade_id}")
                return False
            
            if trade_id in self.closed_trades:
                logger.warning(f"⚠️ [TRADE REGISTRY] محاولة إغلاق صفقة مُغلقة بالفعل: {trade_id}")
                return False
            
            trade = self.trades[trade_id]
            if trade["status"] == TradeStatus.CLOSED.value:
                logger.warning(f"⚠️ [TRADE REGISTRY] الصفقة {trade_id} في حالة CLOSED بالفعل")
                return False
            
            return True
    
    async def close_trade(self, trade_id: str, exit_price: float, 
                         exit_reason: str, closing_worker: str) -> bool:
        """إغلاق الصفقة مع منع التكرار"""
        
        if not await self.can_close_trade(trade_id):
            return False
        
        # استخدام قفل خاص بالصفقة لمنع Race Condition
        async with self.closing_lock[trade_id]:
            # تحقق مرة أخرى بعد الحصول على القفل
            if trade_id in self.closed_trades:
                logger.warning(f"⚠️ [IDEMPOTENCY] الصفقة {trade_id} تم إغلاقها من قبل {self.trades[trade_id]['closing_worker']}")
                return False
            
            async with self.master_lock:
                trade = self.trades[trade_id]
                
                # تحديث بيانات الصفقة
                trade["exit_price"] = exit_price
                trade["exit_reason"] = exit_reason
                trade["closed_at"] = datetime.utcnow().isoformat()
                trade["status"] = TradeStatus.CLOSED.value
                trade["close_count"] += 1
                trade["closing_worker"] = closing_worker
                
                # حساب الـ PnL
                pnl_pct = ((exit_price - trade["entry_price"]) / trade["entry_price"]) * 100
                trade["pnl"] = (trade["amount"] * pnl_pct) / 100
                
                # إضافة الصفقة للصفقات المُغلقة
                self.closed_trades.add(trade_id)
                
                status = "✅ WON" if exit_price >= trade["take_profit"] else "❌ LOST"
                logger.info(
                    f"{status} [TRADE CLOSED] {trade_id} | "
                    f"Entry: {trade['entry_price']} → Exit: {exit_price} | "
                    f"PnL: {trade['pnl']:.2f} | Reason: {exit_reason} | "
                    f"Worker: {closing_worker}"
                )
                
                return True
    
    async def get_trade(self, trade_id: str) -> Optional[dict]:
        """الحصول على بيانات الصفقة"""
        async with self.master_lock:
            return self.trades.get(trade_id)
    
    async def register_event(self, event_id: str) -> bool:
        """تسجيل حدث لمنع معالجة نفس الحدث مرتين"""
        async with self.master_lock:
            if event_id in self.processed_events:
                logger.debug(f"⚠️ [EVENT DEDUP] تم تجاهل حدث مكرر: {event_id}")
                return False
            self.processed_events.add(event_id)
            return True
    
    async def get_statistics(self) -> dict:
        """الحصول على إحصائيات الصفقات"""
        async with self.master_lock:
            total_trades = len(self.trades)
            closed_trades = len(self.closed_trades)
            won_trades = sum(1 for t in self.trades.values() if t["status"] == "WON")
            lost_trades = sum(1 for t in self.trades.values() if t["status"] == "LOST")
            total_pnl = sum(t["pnl"] for t in self.trades.values() if t["status"] == "CLOSED")
            
            return {
                "total_trades": total_trades,
                "closed_trades": closed_trades,
                "open_trades": total_trades - closed_trades,
                "won_trades": won_trades,
                "lost_trades": lost_trades,
                "win_rate": (won_trades / closed_trades * 100) if closed_trades > 0 else 0,
                "total_pnl": total_pnl,
            }

# Global Trade Registry Instance
trade_registry = TradeRegistry()
