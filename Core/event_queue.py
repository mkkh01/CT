import asyncio
import logging
import uuid
import time
from datetime import datetime
from enum import Enum
from typing import Callable, Dict, List, Optional, Any
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
    source: str
    worker_name: str
    priority: int = 1
    
    def to_dict(self):
        return {
            **asdict(self),
            "event_type": self.event_type.value
        }

class EventQueue:
    """طابور أحداث مركزي مرن ومقاوم للانهيار"""
    
    def __init__(self, max_queue_size: int = 10000):
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        self.workers: Dict[str, asyncio.Task] = {}
        self.event_handlers: Dict[EventType, List[Callable]] = {}
        self._processed_events: Dict[str, float] = {}  # TTL Cache: event_id -> expiry_timestamp
        self.master_lock = asyncio.Lock()
        self.is_running = False
        self._semaphore = asyncio.Semaphore(20)  # Bounded concurrency for handlers
        self.event_stats = {
            "total_events": 0,
            "processed_events": 0,
            "failed_events": 0,
            "duplicate_events": 0,
            "events_by_type": {}
        }

    def _clean_ttl_cache(self):
        """تنظيف الذاكرة المؤقتة للأحداث المعالجة"""
        now = time.time()
        expired = [eid for eid, expiry in self._processed_events.items() if now > expiry]
        for eid in expired:
            del self._processed_events[eid]

    async def register_handler(self, event_type: EventType, handler: Callable):
        if event_type not in self.event_handlers:
            self.event_handlers[event_type] = []
        self.event_handlers[event_type].append(handler)
        logger.info(f"✅ [EVENT QUEUE] Registered handler for {event_type.value}: {handler.__name__}")
    
    async def emit_event(self, event_type: EventType, symbol: str, data: dict, 
                        source: str, worker_name: str, priority: int = 1) -> str:
        event_id = f"{event_type.value}_{symbol}_{uuid.uuid4().hex[:8]}"
        
        # التنظيف الدوري للـ TTL cache
        if len(self._processed_events) > 1000:
            self._clean_ttl_cache()

        if event_id in self._processed_events:
            async with self.master_lock:
                self.event_stats["duplicate_events"] += 1
            return event_id
        
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
            self.queue.put_nowait(event)
            async with self.master_lock:
                self.event_stats["total_events"] += 1
                etype = event_type.value
                self.event_stats["events_by_type"][etype] = self.event_stats["events_by_type"].get(etype, 0) + 1
            return event_id
        except asyncio.QueueFull:
            logger.error(f"❌ [EVENT QUEUE] Queue full, dropped event: {event_id}")
            async with self.master_lock:
                self.event_stats["failed_events"] += 1
            return None

    async def process_events(self, worker_id: str):
        logger.info(f"🚀 [EVENT WORKER] Started: {worker_id}")
        
        while self.is_running:
            try:
                event = await self.queue.get()
                
                # TTL Check (10 minutes persistence)
                now = time.time()
                if event.event_id in self._processed_events:
                    if now < self._processed_events[event.event_id]:
                        self.queue.task_done()
                        continue
                
                self._processed_events[event.event_id] = now + 600
                
                handlers = self.event_handlers.get(event.event_type, [])
                for handler in handlers:
                    # Fire-and-forget with bounded concurrency
                    asyncio.create_task(self._safe_run_handler(handler, event))
                
                async with self.master_lock:
                    self.event_stats["processed_events"] += 1
                
                self.queue.task_done()
                
            except Exception as e:
                logger.error(f"❌ [EVENT WORKER ERROR] {worker_id}: {e}")
                await asyncio.sleep(1)

    async def _safe_run_handler(self, handler: Callable, event: Event):
        async with self._semaphore:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await asyncio.wait_for(handler(event), timeout=30)
                else:
                    handler(event)
            except Exception as e:
                logger.error(f"❌ [HANDLER ERROR] {handler.__name__} on {event.event_id}: {e}")
                async with self.master_lock:
                    self.event_stats["failed_events"] += 1

    async def start_workers(self, num_workers: int = 3):
        self.is_running = True
        for i in range(num_workers):
            wid = f"worker_{i}"
            self.workers[wid] = asyncio.create_task(self.process_events(wid))

    async def stop_workers(self):
        self.is_running = False
        # لا نستخدم queue.join() لمنع التعليق
        for wid, task in self.workers.items():
            task.cancel()
        logger.info("✅ [EVENT QUEUE] Workers stopped.")

event_queue = EventQueue()
