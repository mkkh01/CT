import logging
import asyncio
from enum import Enum
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)

class SystemHealth(Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"
    RECOVERING = "RECOVERING"

class DataCompleteness(Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"

@dataclass
class DataHealthCheck:
    """فحص صحة البيانات لرمز معين"""
    symbol: str
    has_klines: bool
    has_websocket_price: bool
    has_order_book: bool
    has_volume_data: bool
    last_update: str
    data_age_seconds: int
    completeness: DataCompleteness
    
    def is_ready(self) -> bool:
        """التحقق من جاهزية البيانات"""
        return (
            self.has_klines and
            self.has_websocket_price and
            self.has_order_book and
            self.has_volume_data and
            self.data_age_seconds < 60  # البيانات يجب أن تكون أقل من دقيقة قديمة
        )

@dataclass
class SystemHealthStatus:
    """حالة صحة النظام العامة"""
    timestamp: str
    overall_health: SystemHealth
    ready_symbols: int
    total_symbols: int
    degraded_symbols: List[str]
    critical_issues: List[str]
    recovery_actions: List[str]
    uptime_seconds: int
    last_analysis_time: Optional[str]
    queue_size: int
    active_workers: int

class StateValidator:
    """نظام التحقق من صحة الحالة والبيانات"""
    
    def __init__(self):
        self.symbol_health: Dict[str, DataHealthCheck] = {}
        self.system_startup_time = datetime.utcnow()
        self.last_health_check = None
        self.health_history: List[SystemHealthStatus] = []
        self.max_history = 100
        self.validation_lock = asyncio.Lock()
        self.auto_recovery_enabled = True
        self.degraded_symbols: set = set()
        self.critical_issues: List[str] = []
    
    async def validate_symbol_data(self, symbol: str, redis_client, 
                                   min_candles: int = 5,
                                   min_price_age: int = 5,
                                   min_order_book_age: int = 10) -> DataHealthCheck:
        """التحقق من صحة بيانات رمز معين"""
        
        async with self.validation_lock:
            now = datetime.utcnow()
            
            # فحص الشموع (Candles/Klines)
            klines_data = redis_client.get_data(f"live_klines_{symbol}")
            has_klines = klines_data is not None and len(klines_data) >= min_candles
            
            # فحص السعر الحي من WebSocket
            price_data = redis_client.get_data(f"live_prices_{symbol}")
            has_websocket_price = price_data is not None
            price_age = self._calculate_age(price_data.get('time') if price_data else None)
            
            # فحص Order Book
            order_book = redis_client.get_data(f"order_book_{symbol}")
            has_order_book = order_book is not None
            order_book_age = self._calculate_age(order_book.get('timestamp') if order_book else None)
            
            # فحص حجم التداول
            volume_data = redis_client.get_data(f"volume_{symbol}")
            has_volume_data = volume_data is not None
            
            # تحديد اكتمال البيانات
            if has_klines and has_websocket_price and has_order_book and has_volume_data:
                completeness = DataCompleteness.COMPLETE
            elif has_klines or has_websocket_price:
                completeness = DataCompleteness.PARTIAL
            else:
                completeness = DataCompleteness.INSUFFICIENT
            
            # حساب سن البيانات (بالثواني)
            data_age = max(price_age, order_book_age)
            
            health_check = DataHealthCheck(
                symbol=symbol,
                has_klines=has_klines,
                has_websocket_price=has_websocket_price,
                has_order_book=has_order_book,
                has_volume_data=has_volume_data,
                last_update=now.isoformat(),
                data_age_seconds=data_age,
                completeness=completeness
            )
            
            self.symbol_health[symbol] = health_check
            
            # تسجيل التحذيرات
            if not has_klines:
                logger.warning(f"⚠️ [DATA VALIDATION] {symbol}: لا توجد بيانات Klines")
            if not has_websocket_price:
                logger.warning(f"⚠️ [DATA VALIDATION] {symbol}: لا توجد أسعار WebSocket")
            if not has_order_book:
                logger.warning(f"⚠️ [DATA VALIDATION] {symbol}: لا توجد بيانات Order Book")
            if not has_volume_data:
                logger.warning(f"⚠️ [DATA VALIDATION] {symbol}: لا توجد بيانات Volume")
            if data_age > 60:
                logger.warning(f"⚠️ [DATA VALIDATION] {symbol}: البيانات قديمة جداً ({data_age}s)")
            
            return health_check
    
    async def validate_system_readiness(self, redis_client, 
                                        required_symbols: List[str],
                                        event_queue=None) -> Tuple[bool, SystemHealthStatus]:
        """التحقق من جاهزية النظام الكامل"""
        
        async with self.validation_lock:
            now = datetime.utcnow()
            critical_issues = []
            recovery_actions = []
            degraded_symbols = []
            ready_count = 0
            
            # فحص جميع الرموز
            for symbol in required_symbols:
                health = await self.validate_symbol_data(symbol, redis_client)
                
                if health.is_ready():
                    ready_count += 1
                else:
                    degraded_symbols.append(symbol)
                    
                    # تسجيل المشكلة
                    if not health.has_klines:
                        critical_issues.append(f"{symbol}: Missing Klines data")
                        recovery_actions.append(f"Restart WebSocket stream for {symbol}")
                    if not health.has_websocket_price:
                        critical_issues.append(f"{symbol}: Missing price data")
                    if not health.has_order_book:
                        critical_issues.append(f"{symbol}: Missing order book")
            
            # حساب الحالة العامة
            readiness_percentage = (ready_count / len(required_symbols) * 100) if required_symbols else 0
            
            if readiness_percentage >= 100:
                overall_health = SystemHealth.HEALTHY
            elif readiness_percentage >= 70:
                overall_health = SystemHealth.DEGRADED
            else:
                overall_health = SystemHealth.CRITICAL
            
            # حساب وقت التشغيل
            uptime = int((now - self.system_startup_time).total_seconds())
            
            # الحصول على إحصائيات ال��ابور
            queue_size = 0
            active_workers = 0
            if event_queue:
                stats = await event_queue.get_stats()
                queue_size = stats.get("queue_size", 0)
                active_workers = stats.get("active_workers", 0)
            
            status = SystemHealthStatus(
                timestamp=now.isoformat(),
                overall_health=overall_health,
                ready_symbols=ready_count,
                total_symbols=len(required_symbols),
                degraded_symbols=degraded_symbols,
                critical_issues=critical_issues,
                recovery_actions=recovery_actions,
                uptime_seconds=uptime,
                last_analysis_time=self.last_health_check,
                queue_size=queue_size,
                active_workers=active_workers
            )
            
            # حفظ في السجل
            self.health_history.append(status)
            if len(self.health_history) > self.max_history:
                self.health_history.pop(0)
            
            # تسجيل الحالة
            self._log_system_status(status)
            
            # تنفيذ إجراءات التعافي التلقائية
            if self.auto_recovery_enabled and overall_health == SystemHealth.CRITICAL:
                await self._execute_recovery_actions(recovery_actions)
            
            is_ready = overall_health == SystemHealth.HEALTHY
            return is_ready, status
    
    async def validate_before_analysis(self, symbol: str, redis_client) -> Tuple[bool, str]:
        """التحقق قبل تنفيذ التحليل"""
        
        health = self.symbol_health.get(symbol)
        
        if not health:
            return False, f"لا توجد بيانات صحة لـ {symbol}"
        
        if health.completeness == DataCompleteness.INSUFFICIENT:
            return False, f"{symbol}: البيانات غير كافية (INSUFFICIENT)"
        
        if health.data_age_seconds > 60:
            return False, f"{symbol}: البيانات قديمة جداً ({health.data_age_seconds}s)"
        
        if not health.has_klines:
            return False, f"{symbol}: لا توجد بيانات Klines"
        
        if not health.has_websocket_price:
            return False, f"{symbol}: لا توجد أسعار WebSocket"
        
        return True, "جاهز للتحليل"
    
    async def validate_before_trade(self, symbol: str, entry_price: float) -> Tuple[bool, str]:
        """التحقق قبل فتح صفقة"""
        
        health = self.symbol_health.get(symbol)
        
        if not health or not health.is_ready():
            return False, f"{symbol}: البيانات غير جاهزة للتداول"
        
        # التحقق من أن السعر معقول
        price_data = self.symbol_health.get(symbol)
        if not price_data:
            return False, "لا توجد بيانات سعر"
        
        return True, "جاهز للتداول"
    
    async def request_symbol_focus(self, symbol: str, redis_client):
        """طلب تركيز النظام على رمز معين"""
        logger.info(f"🎯 [STATE VALIDATOR] طلب تركيز النظام على: {symbol}")
        
        # فحص شامل للرمز
        health = await self.validate_symbol_data(symbol, redis_client)
        
        if not health.is_ready():
            logger.warning(
                f"⚠️ [STATE VALIDATOR] {symbol} غير جاهز:\n"
                f"  - Klines: {health.has_klines}\n"
                f"  - WebSocket Price: {health.has_websocket_price}\n"
                f"  - Order Book: {health.has_order_book}\n"
                f"  - Volume: {health.has_volume_data}\n"
                f"  - Data Age: {health.data_age_seconds}s"
            )
    
    def _calculate_age(self, timestamp_str: Optional[str]) -> int:
        """حساب سن البيانات بالثواني"""
        if not timestamp_str:
            return 999999  # بيانات قديمة جداً
        
        try:
            # محاولة تحليل التنسيق HH:MM:SS
            now = datetime.utcnow()
            time_obj = datetime.strptime(timestamp_str, '%H:%M:%S').time()
            timestamp = datetime.combine(now.date(), time_obj)
            
            age = int((now - timestamp).total_seconds())
            return max(0, age)
        except:
            return 999999
    
    def _log_system_status(self, status: SystemHealthStatus):
        """تسجيل حالة النظام"""
        health_emoji = {
            SystemHealth.HEALTHY: "✅",
            SystemHealth.DEGRADED: "⚠️",
            SystemHealth.CRITICAL: "❌",
            SystemHealth.RECOVERING: "🔄"
        }
        
        emoji = health_emoji.get(status.overall_health, "❓")
        
        logger.info(
            f"{emoji} [SYSTEM HEALTH] {status.overall_health.value} | "
            f"Ready: {status.ready_symbols}/{status.total_symbols} | "
            f"Queue: {status.queue_size} | "
            f"Workers: {status.active_workers} | "
            f"Uptime: {status.uptime_seconds}s"
        )
        
        if status.critical_issues:
            logger.warning(f"🚨 [CRITICAL ISSUES]\n" + "\n".join(f"  - {issue}" for issue in status.critical_issues))
        
        if status.degraded_symbols:
            logger.warning(f"⚠️ [DEGRADED SYMBOLS] {', '.join(status.degraded_symbols)}")
    
    async def _execute_recovery_actions(self, recovery_actions: List[str]):
        """تنفيذ إجراءات التعافي التلقائية"""
        logger.info("🔄 [AUTO RECOVERY] تنفيذ إجراءات التعافي...")
        
        for action in recovery_actions:
            logger.info(f"  ⚡ {action}")
            # يمكن إضافة منطق التعافي هنا
    
    async def get_diagnostics(self) -> dict:
        """الحصول على تقرير تشخيصي شامل"""
        async with self.validation_lock:
            symbol_details = {}
            for symbol, health in self.symbol_health.items():
                symbol_details[symbol] = {
                    "is_ready": health.is_ready(),
                    "completeness": health.completeness.value,
                    "has_klines": health.has_klines,
                    "has_websocket_price": health.has_websocket_price,
                    "has_order_book": health.has_order_book,
                    "has_volume_data": health.has_volume_data,
                    "data_age_seconds": health.data_age_seconds,
                    "last_update": health.last_update,
                }
            
            latest_status = self.health_history[-1] if self.health_history else None
            
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "system_uptime_seconds": int((datetime.utcnow() - self.system_startup_time).total_seconds()),
                "latest_health_status": latest_status.overall_health.value if latest_status else None,
                "symbol_details": symbol_details,
                "health_history_size": len(self.health_history),
                "degraded_symbols": list(self.degraded_symbols),
                "critical_issues": self.critical_issues,
            }

# Global State Validator Instance
state_validator = StateValidator()
