import logging
import asyncio
import json
from datetime import datetime
from typing import Dict, List, Optional
from enum import Enum
from dataclasses import dataclass, asdict

class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

@dataclass
class TradeLog:
    """سجل تفصيلي للصفقة"""
    trade_id: str
    symbol: str
    trade_type: str
    entry_price: float
    stop_loss: float
    take_profit: float
    amount: float
    entry_reason: str
    created_at: str
    created_by_worker: str
    created_by_coroutine: str
    
class CloseLog:
    """سجل إغلاق الصفقة"""
    trade_id: str
    exit_price: float
    exit_reason: str
    closed_at: str
    closed_by_worker: str
    closed_by_coroutine: str
    pnl: float
    duration_seconds: int
    is_duplicate: bool = False
    duplicate_closed_by: Optional[str] = None

@dataclass
class EventLog:
    """سجل الحدث مع تفاصيل الـ Worker"""
    event_id: str
    event_type: str
    symbol: str
    timestamp: str
    source: str
    worker_name: str
    coroutine_name: str
    data: dict
    status: str  # SUCCESS, FAILED, DUPLICATE
    error_message: Optional[str] = None

class DiagnosticLogger:
    """نظام Logging تشخيصي متقدم مع كشف العمليات المكررة"""
    
    def __init__(self, log_file: str = "diagnostic.log"):
        self.trade_logs: Dict[str, TradeLog] = {}
        self.close_logs: Dict[str, List[CloseLog]] = {}  # trade_id -> list of closes
        self.event_logs: List[EventLog] = []
        self.worker_stats: Dict[str, dict] = {}
        self.duplicate_detections: List[str] = []
        self.race_conditions: List[str] = []
        self.max_logs = 10000
        
        # إعداد Logger المركزي
        self.logger = logging.getLogger("DiagnosticLogger")
        self.logger.setLevel(logging.DEBUG)
        
        # File Handler
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        
        # Console Handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        
        # Formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s'
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
    
    async def log_trade_created(self, trade_id: str, symbol: str, trade_type: str,
                               entry_price: float, stop_loss: float, take_profit: float,
                               amount: float, entry_reason: str, worker_name: str) -> None:
        """تسجيل إنشاء صفقة جديدة"""
        
        import asyncio
        import inspect
        
        # الحصول على اسم الـ coroutine
        current_task = asyncio.current_task()
        coroutine_name = current_task.get_name() if current_task else "unknown"
        
        trade_log = TradeLog(
            trade_id=trade_id,
            symbol=symbol,
            trade_type=trade_type,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            amount=amount,
            entry_reason=entry_reason,
            created_at=datetime.utcnow().isoformat(),
            created_by_worker=worker_name,
            created_by_coroutine=coroutine_name,
        )
        
        self.trade_logs[trade_id] = trade_log
        
        self.logger.info(
            f"✅ [TRADE CREATED] {trade_id}\n"
            f"   Symbol: {symbol}\n"
            f"   Type: {trade_type}\n"
            f"   Entry: {entry_price} | SL: {stop_loss} | TP: {take_profit}\n"
            f"   Amount: {amount}\n"
            f"   Reason: {entry_reason}\n"
            f"   Worker: {worker_name}\n"
            f"   Coroutine: {coroutine_name}"
        )
        
        self._update_worker_stats(worker_name, "trades_created", 1)
    
    async def log_trade_close(self, trade_id: str, exit_price: float, exit_reason: str,
                             pnl: float, duration_seconds: int, worker_name: str,
                             is_duplicate: bool = False,
                             duplicate_closed_by: Optional[str] = None) -> None:
        """تسجيل إغلاق الصفقة مع كشف التكرار"""
        
        import asyncio
        
        # الحصول على اسم الـ coroutine
        current_task = asyncio.current_task()
        coroutine_name = current_task.get_name() if current_task else "unknown"
        
        # فحص التكرار
        if trade_id in self.close_logs:
            is_duplicate = True
            self.duplicate_detections.append(
                f"{trade_id} closed multiple times: "
                f"First by {self.close_logs[trade_id][0].closed_by_worker}, "
                f"Now by {worker_name}"
            )
            
            self.logger.warning(
                f"⚠️ [DUPLICATE CLOSE] {trade_id}\n"
                f"   Previous close by: {self.close_logs[trade_id][0].closed_by_worker} "
                f"({self.close_logs[trade_id][0].closed_by_coroutine})\n"
                f"   Current close by: {worker_name} ({coroutine_name})\n"
                f"   Previous exit price: {self.close_logs[trade_id][0].exit_price}\n"
                f"   Current exit price: {exit_price}"
            )
            
            self._update_worker_stats(worker_name, "duplicate_closes_attempted", 1)
            return
        
        close_log = CloseLog(
            trade_id=trade_id,
            exit_price=exit_price,
            exit_reason=exit_reason,
            closed_at=datetime.utcnow().isoformat(),
            closed_by_worker=worker_name,
            closed_by_coroutine=coroutine_name,
            pnl=pnl,
            duration_seconds=duration_seconds,
            is_duplicate=is_duplicate,
            duplicate_closed_by=duplicate_closed_by,
        )
        
        if trade_id not in self.close_logs:
            self.close_logs[trade_id] = []
        
        self.close_logs[trade_id].append(close_log)
        
        status = "✅ WON" if pnl >= 0 else "❌ LOST"
        
        self.logger.info(
            f"{status} [TRADE CLOSED] {trade_id}\n"
            f"   Exit Price: {exit_price}\n"
            f"   PnL: {pnl:.2f}\n"
            f"   Duration: {duration_seconds}s\n"
            f"   Reason: {exit_reason}\n"
            f"   Worker: {worker_name}\n"
            f"   Coroutine: {coroutine_name}"
        )
        
        self._update_worker_stats(worker_name, "trades_closed", 1)
        self._update_worker_stats(worker_name, "total_pnl", pnl)
    
    async def log_event(self, event_id: str, event_type: str, symbol: str,
                       source: str, worker_name: str, data: dict,
                       status: str = "SUCCESS", error_message: Optional[str] = None) -> None:
        """تسجيل حدث مع تفاصيل Worker"""
        
        import asyncio
        
        current_task = asyncio.current_task()
        coroutine_name = current_task.get_name() if current_task else "unknown"
        
        event_log = EventLog(
            event_id=event_id,
            event_type=event_type,
            symbol=symbol,
            timestamp=datetime.utcnow().isoformat(),
            source=source,
            worker_name=worker_name,
            coroutine_name=coroutine_name,
            data=data,
            status=status,
            error_message=error_message,
        )
        
        self.event_logs.append(event_log)
        
        if len(self.event_logs) > self.max_logs:
            self.event_logs.pop(0)
        
        if status == "SUCCESS":
            emoji = "✅"
        elif status == "DUPLICATE":
            emoji = "⚠️"
        else:
            emoji = "❌"
        
        log_msg = (
            f"{emoji} [EVENT] {event_type} | {symbol} | {source}\n"
            f"   Event ID: {event_id}\n"
            f"   Worker: {worker_name}\n"
            f"   Coroutine: {coroutine_name}\n"
            f"   Status: {status}"
        )
        
        if error_message:
            log_msg += f"\n   Error: {error_message}"
        
        if status == "SUCCESS":
            self.logger.info(log_msg)
        elif status == "DUPLICATE":
            self.logger.warning(log_msg)
        else:
            self.logger.error(log_msg)
        
        self._update_worker_stats(worker_name, "events_processed", 1)
        if status == "DUPLICATE":
            self._update_worker_stats(worker_name, "duplicate_events", 1)
        if status == "FAILED":
            self._update_worker_stats(worker_name, "failed_events", 1)
    
    async def log_race_condition_detected(self, trade_id: str, worker1: str,
                                         worker2: str, operation: str) -> None:
        """تسجيل اكتشاف Race Condition"""
        
        race_msg = (
            f"Race Condition Detected: {trade_id}\n"
            f"  Operation: {operation}\n"
            f"  Worker 1: {worker1}\n"
            f"  Worker 2: {worker2}"
        )
        
        self.race_conditions.append(race_msg)
        
        self.logger.critical(f"🚨 [RACE CONDITION] {race_msg}")
    
    async def log_concurrent_operation(self, trade_id: str, operation: str,
                                      worker_name: str, duration_ms: int) -> None:
        """تسجيل العملية المتزامنة"""
        
        self.logger.debug(
            f"⚡ [CONCURRENT OP] {trade_id} | Operation: {operation} | "
            f"Worker: {worker_name} | Duration: {duration_ms}ms"
        )
    
    def _update_worker_stats(self, worker_name: str, metric: str, value: float = 1) -> None:
        """تحديث إحصائيات الـ Worker"""
        
        if worker_name not in self.worker_stats:
            self.worker_stats[worker_name] = {
                "trades_created": 0,
                "trades_closed": 0,
                "duplicate_closes_attempted": 0,
                "events_processed": 0,
                "duplicate_events": 0,
                "failed_events": 0,
                "total_pnl": 0.0,
            }
        
        if metric in self.worker_stats[worker_name]:
            self.worker_stats[worker_name][metric] += value
    
    async def get_diagnostics_report(self) -> dict:
        """الحصول على تقرير تشخيصي شامل"""
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "total_trades": len(self.trade_logs),
            "closed_trades": len(self.close_logs),
            "open_trades": len(self.trade_logs) - len(self.close_logs),
            "duplicate_close_attempts": len(self.duplicate_detections),
            "race_conditions_detected": len(self.race_conditions),
            "worker_statistics": self.worker_stats,
            "recent_duplicates": self.duplicate_detections[-10:],  # آخر 10 حالات تكرار
            "recent_race_conditions": self.race_conditions[-10:],  # آخر 10 Race Conditions
            "total_events_logged": len(self.event_logs),
        }
    
    async def export_trade_history(self, output_file: str = "trade_history.json") -> None:
        """تصدير سجل الصفقات الكامل"""
        
        export_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "trades": {
                trade_id: {
                    **asdict(trade_log),
                    "closes": [
                        asdict(close_log) for close_log in self.close_logs.get(trade_id, [])
                    ]
                }
                for trade_id, trade_log in self.trade_logs.items()
            },
            "diagnostics": await self.get_diagnostics_report(),
        }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)
        
        self.logger.info(f"📊 [EXPORT] Trade history exported to {output_file}")
    
    async def print_summary(self) -> None:
        """طباعة ملخص التشخيص"""
        
        report = await self.get_diagnostics_report()
        
        summary = (
            f"\n{'='*80}\n"
            f"📊 DIAGNOSTIC SUMMARY\n"
            f"{'='*80}\n"
            f"Total Trades: {report['total_trades']}\n"
            f"Closed Trades: {report['closed_trades']}\n"
            f"Open Trades: {report['open_trades']}\n"
            f"Duplicate Close Attempts: {report['duplicate_close_attempts']}\n"
            f"Race Conditions Detected: {report['race_conditions_detected']}\n"
            f"Total Events: {report['total_events_logged']}\n"
            f"\n--- Worker Statistics ---\n"
        )
        
        for worker, stats in report['worker_statistics'].items():
            summary += (
                f"\n{worker}:\n"
                f"  Created: {stats['trades_created']}\n"
                f"  Closed: {stats['trades_closed']}\n"
                f"  Duplicate Attempts: {stats['duplicate_closes_attempted']}\n"
                f"  Events Processed: {stats['events_processed']}\n"
                f"  Failed Events: {stats['failed_events']}\n"
                f"  Total PnL: {stats['total_pnl']:.2f}\n"
            )
        
        if report['recent_duplicates']:
            summary += f"\n--- Recent Duplicates ---\n"
            for dup in report['recent_duplicates'][-5:]:
                summary += f"  ⚠️ {dup}\n"
        
        if report['recent_race_conditions']:
            summary += f"\n--- Recent Race Conditions ---\n"
            for race in report['recent_race_conditions'][-5:]:
                summary += f"  🚨 {race}\n"
        
        summary += f"{'='*80}\n"
        
        self.logger.info(summary)

# Global Diagnostic Logger Instance
diagnostic_logger = DiagnosticLogger()
