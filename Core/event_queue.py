import asyncio
import logging
import uuid
from datetime import datetime
from enum import Enum
from typing import Callable, Dict, List, Optional
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

class EventType(Enum):
    TRADE_OPENED = "TRADE_OPENED"
    TRADE_CLOSED = "TRADE_CLOSED"
    SHADOW_TRADE_CLOSED = "SHADOW_TRADE_CLOSED"
    PRICE_UPDATE = "PRICE_UPDATE"
    KLINE_UPDATE = "KLINE_UPDATE"
    ANALYSIS_COMPLETE = "ANALYSIS_COMPLETE"
    WARMUP_PROGRESS = "WARMUP_PROGRESS"
    STATE_CHANGE = "STATE_CHANGE"
    ERROR_OCCURRED = "ERROR_OCCURRED"

@dataclass
class Event:
    """البنية الأساسية للحدث"""
    event_id: str
    event_type: EventType
    symbol: str
    timestamp: str
    data: dict
    source: str  # "TRADE_MONITOR", "SHADOW_MONITOR", "AI_ENGINE", etc.
    worker_name: str  # اسم الـ coroutine أو thread الذي أنشأ الحدث
    priority: int = 1  # 1=low, 5=high
    
    def to_dict(self):
        return {
            **asdict(self),
            "event_type": self.event_type.value
        }

class EventQueue:
    """طابور أحداث مركزي مع Worker Manager"""
    
    def __init__(self, max_queue_size: int = 10000):
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        self.workers: Dict[str, asyncio.Task] = {}
        self.event_handlers: Dict[EventType, List[Callable]] = {}
        self.processed_events: set = set()  # منع معالجة نفس الحدث مرتين
        self.master_lock = asyncio.Lock()
        self.is_running = False
        self.event_stats = {
            "total_events": 0,
            "processed_events": 0,
            "failed_events": 0,
            "duplicate_events": 0,
            "events_by_type": {}
        }
    
    async def register_handler(self, event_type: EventType, handler: Callable):
        """تسجيل معالج للحدث"""
        if event_type not in self.event_handlers:
            self.event_handlers[event_type] = []
        self.event_handlers[event_type].append(handler)
        logger.info(f"✅ [EVENT QUEUE] تم تسجيل معالج لـ {event_type.value}: {handler.__name__}")
    
    async def emit_event(self, event_type: EventType, symbol: str, data: dict, 
                        source: str, worker_name: str, priority: int = 1) -> str:
        """إرسال حدث جديد إلى الطابور"""
        event_id = f"{event_type.value}_{symbol}_{uuid.uuid4().hex[:8]}"
        
        event = Event(
            event_id=event_id,
            event_type=event_type,
            symbol=symbol,
            timestamp=datetime.utcnow().isoformat(),
            data=data,
            source=source,
            worker_name=worker_name,
            priority=priority
        )
        
        try:
            # تجنب الأحداث المكررة
            if event_id in self.processed_events:
                async with self.master_lock:
                    self.event_stats["duplicate_events"] += 1
                logger.debug(f"⚠️ [EVENT DEDUP] تم تجاهل حدث مكرر: {event_id}")
                return event_id
            
            await self.queue.put(event)
            async with self.master_lock:
                self.event_stats["total_events"] += 1
                if event_type.value not in self.event_stats["events_by_type"]:
                    self.event_stats["events_by_type"][event_type.value] = 0
                self.event_stats["events_by_type"][event_type.value] += 1
            
            logger.debug(
                f"📤 [EVENT EMIT] {event_type.value} | Symbol: {symbol} | "
                f"Source: {source} | Worker: {worker_name}"
            )
            
            return event_id
        except asyncio.QueueFull:
            logger.error(f"❌ [EVENT QUEUE] الطابور ممتلئ، تم تجاهل الحدث: {event_id}")
            async with self.master_lock:
                self.event_stats["failed_events"] += 1
            return None
    
    async def process_events(self, worker_id: str = "default_worker"):
        """معالج الأحداث الرئيسي"""
        logger.info(f"🚀 [EVENT WORKER] بدء معالج الأحداث: {worker_id}")
        
        while self.is_running:
            try:
                # الحصول على الحدث من الطابور مع timeout
                event = await asyncio.wait_for(self.queue.get(), timeout=5.0)
                
                # منع معالجة الحدث مرتين
                if event.event_id in self.processed_events:
                    logger.debug(f"⚠️ [DEDUP] تم تجاهل حدث مكرر: {event.event_id}")
                    async with self.master_lock:
                        self.event_stats["duplicate_events"] += 1
                    continue
                
                async with self.master_lock:
                    self.processed_events.add(event.event_id)
                
                # تنفيذ جميع معالجات الحدث
                handlers = self.event_handlers.get(event.event_type, [])
                
                if not handlers:
                    logger.warning(
                        f"⚠️ [EVENT] لا توجد معالجات للحدث: {event.event_type.value}"
                    )
                    async with self.master_lock:
                        self.event_stats["processed_events"] += 1
                    self.queue.task_done()
                    continue
                
                # تنفيذ المعالجات بالتوازي
                tasks = []
                for handler in handlers:
                    task = asyncio.create_task(
                        self._safe_execute_handler(handler, event, worker_id)
                    )
                    tasks.append(task)
                
                # انتظار انتهاء جميع المعالجات
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # تسجيل النتائج
                for result in results:
                    if isinstance(result, Exception):
                        logger.error(
                            f"❌ [EVENT HANDLER ERROR] {event.event_id}: {result}"
                        )
                        async with self.master_lock:
                            self.event_stats["failed_events"] += 1
                
                async with self.master_lock:
                    self.event_stats["processed_events"] += 1
                
                logger.debug(
                    f"✅ [EVENT PROCESSED] {event.event_id} | Type: {event.event_type.value} | "
                    f"Handlers: {len(handlers)} | Worker: {worker_id}"
                )
                
                self.queue.task_done()
                
            except asyncio.TimeoutError:
                # لا توجد أحداث جديدة
                continue
            except Exception as e:
                logger.error(f"❌ [EVENT QUEUE ERROR] {e}")
                async with self.master_lock:
                    self.event_stats["failed_events"] += 1
    
    async def _safe_execute_handler(self, handler: Callable, event: Event, worker_id: str):
        """تنفيذ آمن للمعالج مع معالجة الأخطاء"""
        try:
            if asyncio.iscoroutinefunction(handler):
                await handler(event)
            else:
                handler(event)
        except Exception as e:
            logger.error(
                f"❌ [HANDLER EXCEPTION] Handler: {handler.__name__} | "
                f"Event: {event.event_id} | Error: {e}"
            )
            raise
    
    async def start_workers(self, num_workers: int = 3):
        """بدء عدد من معالجات الأحداث"""
        self.is_running = True
        
        for i in range(num_workers):
            worker_id = f"event_worker_{i}"
            task = asyncio.create_task(self.process_events(worker_id))
            self.workers[worker_id] = task
            logger.info(f"✅ [EVENT QUEUE] تم بدء معالج: {worker_id}")
    
    async def stop_workers(self):
        """إيقاف جميع معالجات الأحداث"""
        self.is_running = False
        
        # انتظار انتهاء جميع الأحداث في الطابور
        await self.queue.join()
        
        # إلغاء جميع المعالجات
        for worker_id, task in self.workers.items():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        logger.info("✅ [EVENT QUEUE] تم إيقاف جميع معالجات الأحداث")
    
    async def get_stats(self) -> dict:
        """الحصول على إحصائيات الطابور"""
        async with self.master_lock:
            return {
                **self.event_stats,
                "queue_size": self.queue.qsize(),
                "active_workers": len(self.workers),
            }
    
    async def wait_queue_empty(self, timeout: Optional[float] = None):
        """انتظار إفراغ الطابور"""
        try:
            await asyncio.wait_for(self.queue.join(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"⚠️ [EVENT QUEUE] انتهت مهلة انتظار الطابور الفارغ")

# Global Event Queue Instance
event_queue = EventQueue()
