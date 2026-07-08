
"""
══════════════════════════════════════════════════════════════════════
CT V4.0 — FULL TRANSPARENCY OBSERVABILITY SYSTEM
══════════════════════════════════════════════════════════════════════

Log levels (set via OBSERVABILITY_LEVEL env var):
  NORMAL  — startup, errors, trade signals, price snapshot every 60s
  DEBUG   — per-cycle: indicators, SMC, strategy scores, decision checklist
  TRACE   — every tick, every candle, every DB write, every cache op

Usage:
    from Core.observability import Obs, Level

    obs = Obs.get()

    # Startup
    obs.startup_banner()
    obs.system_snapshot(...)

    # Price stream
    obs.price_tick(symbol, price, ...)

    # Decision
    obs.decision_report(...)

    # Trade lifecycle
    obs.trade_opened(...)
    obs.trade_closed(...)

    # Errors
    obs.error_full(...)

    # API
    obs.binance_status(...)
    obs.db_query(...)
    obs.cache_op(...)

    # Performance
    with obs.timer("Data Fetch"):
        result = await fetch_data()
"""

import os
import sys
import json
import time
import logging
import platform
import traceback
import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union
from functools import wraps

# ═══════════════════════════════════════════════════════════════════
# Log Levels
# ═══════════════════════════════════════════════════════════════════

class Level(Enum):
    NORMAL = 0  # startup, errors, trades, price every 60s
    DEBUG  = 1  # per-cycle: indicators, SMC, scores, checklist
    TRACE  = 2  # every tick, candle, DB write, cache op


_LEVEL_MAP = {
    "normal": Level.NORMAL,
    "debug": Level.DEBUG,
    "trace": Level.TRACE,
}

_current_level = _LEVEL_MAP.get(
    os.environ.get("OBSERVABILITY_LEVEL", "normal").strip().lower(),
    Level.NORMAL,
)

def set_level(level: Level):
    global _current_level
    _current_level = level

def get_level() -> Level:
    return _current_level

def is_level(level: Level) -> bool:
    return _current_level.value >= level.value

def is_debug() -> bool:
    return is_level(Level.DEBUG)

def is_trace() -> bool:
    return is_level(Level.TRACE)


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════

_SEP55 = "─" * 55
_SEP40 = "─" * 40

_ICON_OK = "✅"
_ICON_FAIL = "❌"
_ICON_WARN = "⚠️"
_ICON_INFO = "ℹ️"

def _icon(ok: bool) -> str:
    return _ICON_OK if ok else _ICON_FAIL

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

def _fmt_ts(ts) -> str:
    if ts is None or ts == 0:
        return "N/A"
    try:
        if isinstance(ts, (int, float)):
            if ts > 1e12:
                ts = ts / 1000
            return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M:%S")
        return str(ts)
    except Exception:
        return str(ts)

def _fmt_price(p, prec=4) -> str:
    """Format a price value safely."""
    if p is None:
        return "N/A"
    try:
        return f"{float(p):.{prec}f}"
    except (ValueError, TypeError):
        return str(p)

def _fmt_pct(v) -> str:
    if v is None:
        return "N/A"
    try:
        return f"{float(v):+.3f}%"
    except (ValueError, TypeError):
        return str(v)

def _divider(title: str = "") -> str:
    if title:
        return f"\n{'─'*20} {title} {'─'*(55-len(title)-22)}"
    return "\n" + _SEP55

def _print_box(title: str, lines: List[str]):
    """Print a boxed section."""
    buf = [_divider(title)]
    for line in lines:
        buf.append(f"  {line}")
    buf.append(_SEP55)
    info(buf)

def _kv(k: str, v: Any, indent: int = 2) -> str:
    return f"{' ' * indent}{k:<18s} {v}"

def _log(msg: str):
    """Print to stdout with immediate flush for Render."""
    print(msg, flush=True)


def info(lines: List[str]):
    for line in lines:
        _log(line)


# ═══════════════════════════════════════════════════════════════════
# Structured JSON sink (writes to file when configured)
# ═══════════════════════════════════════════════════════════════════

_JSON_LOG_PATH = os.environ.get("OBS_JSON_LOG", "")

def _json_event(event_type: str, data: Dict[str, Any]):
    """Emit a structured JSON event to file if configured."""
    if not _JSON_LOG_PATH:
        return
    try:
        event = {
            "ts": time.time(),
            "ts_iso": _now_iso(),
            "type": event_type,
            "data": data,
        }
        with open(_JSON_LOG_PATH, "a") as f:
            f.write(json.dumps(event, default=str) + "\n")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════
# Performance timer context manager
# ═══════════════════════════════════════════════════════════════════

class PerfTimer:
    """Context manager / decorator for measuring execution time."""

    def __init__(self, label: str, obs=None):
        self.label = label
        self._obs = obs
        self._start = 0
        self.elapsed = 0

    def __enter__(self):
        self._start = time.time()
        return self

    def __exit__(self, *args):
        self.elapsed = time.time() - self._start
        if is_debug():
            _log(_kv(f"[PERF] {self.label}", f"{self.elapsed:.4f}s", indent=0))

    def __call__(self, func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            with PerfTimer(self.label):
                return await func(*args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            with PerfTimer(self.label):
                return func(*args, **kwargs)

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper


# ═══════════════════════════════════════════════════════════════════
# Main Observability Hub
# ═══════════════════════════════════════════════════════════════════

class _Obs:
    """Singleton observability hub for CT trading system."""

    def __init__(self):
        self._started_at = time.time()
        self._price_cache: Dict[str, float] = {}
        self._price_last_ts: Dict[str, float] = {}
        self._price_last_seen: Dict[str, float] = {}
        self._last_snapshot: float = 0
        self._last_price_diag: float = 0
        self._ws_msg_count: int = 0
        self._ws_last_msg: float = 0
        self._ws_reconnects: int = 0
        self._api_rest_count: int = 0
        self._last_rest_call: float = 0

    # ══════════════════════════════════════════════════════════════
    # 1. STARTUP & SYSTEM
    # ══════════════════════════════════════════════════════════════

    def startup_banner(self):
        info([
            "",
            "╔" + "═" * 53 + "╗",
            "║" + "   CT INSTITUTIONAL TRADING SYSTEM  V4.0".center(53) + "║",
            "╚" + "═" * 53 + "╝",
            f"  {_kv('Environment', os.environ.get('RENDER', 'local'), indent=0)}",
            f"  {_kv('Python', platform.python_version(), indent=0)}",
            f"  {_kv('PID', str(os.getpid()), indent=0)}",
            f"  {_kv('Started', _now_iso(), indent=0)}",
            f"  {_kv('Commit', os.environ.get('RENDER_GIT_COMMIT', 'N/A'), indent=0)}",
            f"  {_kv('Branch', os.environ.get('RENDER_GIT_BRANCH', 'N/A'), indent=0)}",
            f"  {_kv('Obs Level', _current_level.name, indent=0)}",
            _SEP55,
        ])
        _json_event("startup", {
            "env": os.environ.get("RENDER", "local"),
            "python": platform.python_version(),
            "pid": os.getpid(),
            "commit": os.environ.get("RENDER_GIT_COMMIT", "N/A"),
            "branch": os.environ.get("RENDER_GIT_BRANCH", "N/A"),
            "level": _current_level.name,
        })

    def startup_report(self, components: Dict[str, bool]):
        all_ok = all(components.values())
        lines = [
            _divider("SYSTEM STARTUP REPORT"),
        ]
        for name, ok in components.items():
            lines.append(f"  {_icon(ok)} {name}")
        lines.append(f"  {'─'*30}")
        lines.append(f"  {'✅' if all_ok else '❌'} SYSTEM " + ("READY" if all_ok else "HAS ISSUES"))
        lines.append(_SEP55)
        info(lines)

    def startup_step(self, step_num: int, total_steps: int, name: str, status: str = "START", elapsed_s: float = 0, detail: str = ""):
        if status == "START":
            _log(f"[STARTUP] [{step_num}/{total_steps}] {name}...")
        elif status == "SUCCESS":
            _log(f"[STARTUP] [{step_num}/{total_steps}] {name} SUCCESS ({elapsed_s:.3f}s)")
        elif status == "FAILED":
            _log(f"[STARTUP] [{step_num}/{total_steps}] {name} FAILED ({elapsed_s:.3f}s) {detail}")
        _json_event("startup_step", {
            "step": step_num, "total": total_steps, "name": name, "status": status, "elapsed": elapsed_s, "detail": detail
        })

    def constructor_log(self, class_name: str, method_name: str, message: str, level: str = "info"):
        _log(f"[CONSTRUCTOR] {class_name}.{method_name}: {message}")
        _json_event("constructor_log", {
            "class": class_name, "method": method_name, "message": message, "level": level
        })

    def task_status_report(self, task_name: str, status: Dict[str, Any]):
        if not is_debug():
            return
        lines = [_divider(f"ASYNC TASK STATUS — {task_name}")]
        for k, v in status.items():
            lines.append(_kv(k, str(v)))
        lines.append(_SEP55)
        info(lines)
        _json_event("task_status", {
            "task_name": task_name, "status": status
        })

    def task_crash_report(self, task_name: str, why: str, where: str, traceback_str: str, local_vars: Dict[str, Any], task_creator: str):
        lines = [
            _divider(f"{_ICON_FAIL} ASYNC TASK CRASH — {task_name}"),
            _kv("WHY", why),
            _kv("WHERE", where),
            _kv("TASK CREATOR", task_creator),
            _kv("LOCAL VARIABLES", json.dumps(local_vars, default=str)[:200] + "..."),
            _divider("TRACEBACK"),
        ]
        for line in traceback_str.splitlines():
            lines.append(f"  {line}")
        lines.append(_SEP55)
        info(lines)
        _json_event("task_crash", {
            "task_name": task_name, "why": why, "where": where, "local_vars": local_vars, "task_creator": task_creator, "traceback": traceback_str
        })

    def heartbeat_update(self, module: str, last_activity: float, current_state: str, last_exception: str = "", restart_count: int = 0, last_symbol: str = "", current_symbol: str = "", loop_count: int = 0, iteration: int = 0, execution_time: float = 0, current_stage: str = ""):
        if not is_debug():
            return
        info([
            _divider(f"HEARTBEAT — {module}"),
            _kv("Last Activity", _fmt_ts(last_activity)),
            _kv("Current State", current_state),
            _kv("Last Exception", last_exception if last_exception else "N/A"),
            _kv("Restart Count", restart_count),
            _kv("Last Symbol", last_symbol if last_symbol else "N/A"),
            _kv("Current Symbol", current_symbol if current_symbol else "N/A"),
            _kv("Loop Count", loop_count),
            _kv("Iteration", iteration),
            _kv("Execution Time", f"{execution_time:.3f}s"),
            _kv("Current Stage", current_stage if current_stage else "N/A"),
            _SEP55,
        ])
        _json_event("heartbeat_update", {
            "module": module, "last_activity": last_activity, "current_state": current_state, "last_exception": last_exception,
            "restart_count": restart_count, "last_symbol": last_symbol, "current_symbol": current_symbol, "loop_count": loop_count,
            "iteration": iteration, "execution_time": execution_time, "current_stage": current_stage
        })

    def trademonitor_loop_log(self, loop_num: int, current_symbol: str, current_time: str, db_status: str, redis_status: str, exchange_status: str, binance_status: str, ws_status: str, cache_status: str, strategy_count: int, open_positions: int, pending_signals: int, current_candle: str, last_candle_time: str, current_price: float, spread: float, latency: float, memory_usage: float, cpu_usage: float):
        if not is_debug():
            return
        info([
            _divider(f"TRADEMONITOR LOOP #{loop_num}"),
            _kv("Current Symbol", current_symbol),
            _kv("Current Time", current_time),
            _kv("Database Status", db_status),
            _kv("Redis Status", redis_status),
            _kv("Exchange Status", exchange_status),
            _kv("Binance Status", binance_status),
            _kv("WebSocket Status", ws_status),
            _kv("Cache Status", cache_status),
            _kv("Strategy Count", strategy_count),
            _kv("Open Positions", open_positions),
            _kv("Pending Signals", pending_signals),
            _kv("Current Candle", current_candle),
            _kv("Last Candle Time", last_candle_time),
            _kv("Current Price", _fmt_price(current_price)),
            _kv("Spread", f"{spread:.8f}"),
            _kv("Latency", f"{latency:.2f}ms"),
            _kv("Memory Usage", f"{memory_usage:.2f}MB"),
            _kv("CPU Usage", f"{cpu_usage:.2f}%"),
            _SEP55,
        ])
        _json_event("trademonitor_loop", {
            "loop_num": loop_num, "current_symbol": current_symbol, "current_time": current_time, "db_status": db_status,
            "redis_status": redis_status, "exchange_status": exchange_status, "binance_status": binance_status, "ws_status": ws_status,
            "cache_status": cache_status, "strategy_count": strategy_count, "open_positions": open_positions,
            "pending_signals": pending_signals, "current_candle": current_candle, "last_candle_time": last_candle_time,
            "current_price": current_price, "spread": spread, "latency": latency, "memory_usage": memory_usage, "cpu_usage": cpu_usage
        })

    def websocket_event(self, event_type: str, **kwargs):
        if not is_trace():
            return
        info([
            _divider(f"WEBSOCKET — {event_type}"),
            *[_kv(k, str(v)) for k, v in kwargs.items()],
            _SEP55,
        ])
        _json_event("websocket_event", {
            "event_type": event_type, **kwargs
        })

    def live_price_tick_full(self, exchange: str, symbol: str, bid: float, ask: float, last_price: float, mark_price: float, volume: float, timestamp: float, latency: float, redis_write_status: str, cache_update_status: str, database_update_status: str, telegram_broadcast_status: str):
        if not is_trace():
            return
        info([
            _divider(f"LIVE PRICE TICK — {symbol}"),
            _kv("Exchange", exchange),
            _kv("Symbol", symbol),
            _kv("Bid", _fmt_price(bid)),
            _kv("Ask", _fmt_price(ask)),
            _kv("Last Price", _fmt_price(last_price)),
            _kv("Mark Price", _fmt_price(mark_price)),
            _kv("Volume", f"{volume:.2f}"),
            _kv("Time", _fmt_ts(timestamp)),
            _kv("Latency", f"{latency:.2f}ms"),
            _kv("Redis Write Status", redis_write_status),
            _kv("Cache Update Status", cache_update_status),
            _kv("Database Update Status", database_update_status),
            _kv("Telegram Broadcast Status", telegram_broadcast_status),
            _SEP55,
        ])
        _json_event("live_price_tick_full", {
            "exchange": exchange, "symbol": symbol, "bid": bid, "ask": ask, "last_price": last_price, "mark_price": mark_price,
            "volume": volume, "timestamp": timestamp, "latency": latency, "redis_write_status": redis_write_status,
            "cache_update_status": cache_update_status, "database_update_status": database_update_status, "telegram_broadcast_status": telegram_broadcast_status
        })

    def db_query_full(self, sql: str, execution_time: float, rows: int, connection_id: str, pool_status: str, retry_count: int, errors: str = ""):
        if not is_trace():
            return
        info([
            _divider("DATABASE QUERY"),
            _kv("SQL", sql[:100] + "..."),
            _kv("Execution Time", f"{execution_time:.3f}s"),
            _kv("Rows", rows),
            _kv("Connection ID", connection_id),
            _kv("Pool Status", pool_status),
            _kv("Retry Count", retry_count),
            _kv("Errors", errors if errors else "N/A"),
            _SEP55,
        ])
        _json_event("db_query_full", {
            "sql": sql, "execution_time": execution_time, "rows": rows, "connection_id": connection_id,
            "pool_status": pool_status, "retry_count": retry_count, "errors": errors
        })

    def db_tracked_coins_load(self, coins_found: int, coins_ignored: int, reason: str, user_ids: List[int], capital: float, risk: float, timeframe: str):
        if not is_debug():
            return
        info([
            _divider("DATABASE TRACKED COINS LOAD"),
            _kv("Coins Found", coins_found),
            _kv("Coins Ignored", coins_ignored),
            _kv("Reason", reason),
            _kv("User IDs", str(user_ids)),
            _kv("Capital", f"{capital:.2f}"),
            _kv("Risk", f"{risk:.2f}"),
            _kv("Timeframe", timeframe),
            _SEP55,
        ])
        _json_event("db_tracked_coins_load", {
            "coins_found": coins_found, "coins_ignored": coins_ignored, "reason": reason, "user_ids": user_ids,
            "capital": capital, "risk": risk, "timeframe": timeframe
        })

    def strategy_execution(self, strategy_name: str, started_at: float, finished_at: float, execution_time: float, signal: str, confidence: float, reasons: List[str], internal_indicators: Dict[str, Any]):
        if not is_debug():
            return
        info([
            _divider(f"STRATEGY EXECUTION — {strategy_name}"),
            _kv("Started At", _fmt_ts(started_at)),
            _kv("Finished At", _fmt_ts(finished_at)),
            _kv("Execution Time", f"{execution_time:.3f}s"),
            _kv("Signal", signal),
            _kv("Confidence", f"{confidence:.2f}%"),
            _kv("Reasons", ", ".join(reasons)),
            _kv("Internal Indicators", json.dumps(internal_indicators, default=str)[:200] + "..."),
            _SEP55,
        ])
        _json_event("strategy_execution", {
            "strategy_name": strategy_name, "started_at": started_at, "finished_at": finished_at, "execution_time": execution_time,
            "signal": signal, "confidence": confidence, "reasons": reasons, "internal_indicators": internal_indicators
        })

    def indicator_calculation(self, indicator_name: str, values: Dict[str, Any]):
        if not is_trace():
            return
        info([
            _divider(f"INDICATOR CALCULATION — {indicator_name}"),
            *[_kv(k, str(v)) for k, v in values.items()],
            _SEP55,
        ])
        _json_event("indicator_calculation", {
            "indicator_name": indicator_name, "values": values
        })

    def decision_rule_evaluation(self, rule_name: str, status: str, reason: str = ""):
        if not is_debug():
            return
        info([
            _kv(f"DECISION RULE — {rule_name}", f"{status} {reason}")
        ])
        _json_event("decision_rule_evaluation", {
            "rule_name": rule_name, "status": status, "reason": reason
        })

    def trademonitor_crash_report(self, death_time: float, uptime: float, loop_number: int, current_symbol: str, last_price: float, last_function: str, last_exception: str, stack_trace: str, task_state: Dict[str, Any], redis_status: str, database_status: str, exchange_status: str, websocket_status: str, heartbeat_status: Dict[str, Any], memory: float, cpu: float, restart_count: int, reason: str):
        lines = [
            "",
            "╔" + "═" * 53 + "╗",
            "║  ========== TRADE MONITOR CRASH REPORT ==========".ljust(54) + "║",
            "╠" + "═" * 53 + "╣",
            _kv("Death Time", _fmt_ts(death_time)),
            _kv("Uptime", f"{uptime:.0f}s"),
            _kv("Loop Number", loop_number),
            _kv("Current Symbol", current_symbol),
            _kv("Last Price", _fmt_price(last_price)),
            _kv("Last Function", last_function),
            _kv("Last Exception", last_exception),
            _kv("Task State", json.dumps(task_state, default=str)[:200] + "..."),
            _kv("Redis Status", redis_status),
            _kv("Database Status", database_status),
            _kv("Exchange Status", exchange_status),
            _kv("WebSocket Status", websocket_status),
            _kv("Heartbeat Status", json.dumps(heartbeat_status, default=str)[:200] + "..."),
            _kv("Memory", f"{memory:.2f}MB"),
            _kv("CPU", f"{cpu:.2f}%"),
            _kv("Restart Count", restart_count),
            _kv("Reason", reason),
            _divider("STACK TRACE"),
        ]
        for line in stack_trace.splitlines():
            lines.append(f"  {line}")
        lines.append("╚" + "═" * 53 + "╝")
        info(lines)
        _json_event("trademonitor_crash_report", {
            "death_time": death_time, "uptime": uptime, "loop_number": loop_number, "current_symbol": current_symbol,
            "last_price": last_price, "last_function": last_function, "last_exception": last_exception, "stack_trace": stack_trace,
            "task_state": task_state, "redis_status": redis_status, "database_status": database_status, "exchange_status": exchange_status,
            "websocket_status": websocket_status, "heartbeat_status": heartbeat_status, "memory": memory, "cpu": cpu,
            "restart_count": restart_count, "reason": reason
        })

    def restart_event(self, why: str, who: str, task_state: Dict[str, Any], old_task_id: str, new_task_id: str, duration: float, result: str):
        info([
            _divider(f"RESTART EVENT"),
            _kv("Why Restart", why),
            _kv("Who Requested", who),
            _kv("Task State", json.dumps(task_state, default=str)[:200] + "..."),
            _kv("Old Task ID", old_task_id),
            _kv("New Task ID", new_task_id),
            _kv("Duration", f"{duration:.3f}s"),
            _kv("Result", result),
            _SEP55,
        ])
        _json_event("restart_event", {
            "why": why, "who": who, "task_state": task_state, "old_task_id": old_task_id,
            "new_task_id": new_task_id, "duration": duration, "result": result
        })

    def system_dashboard_update(self, trademonitor_status: str, ai_engine_status: str, decision_engine_status: str, risk_engine_status: str, database_status: str, redis_status: str, telegram_status: str, exchange_status: str, websocket_status: str, live_prices_status: str, tracked_symbols_count: int, open_trades_count: int, cpu_usage: float, ram_usage: float, heartbeat_status: str, last_tick_time: float, last_candle_time: float, reconnect_count: int, restart_count: int):
        info([
            "",
            "╔" + "═" * 53 + "╗",
            "║  ========== SYSTEM STATUS DASHBOARD ==========".ljust(54) + "║",
            "╠" + "═" * 53 + "╣",
            _kv("TradeMonitor", trademonitor_status),
            _kv("AI Engine", ai_engine_status),
            _kv("Decision Engine", decision_engine_status),
            _kv("Risk Engine", risk_engine_status),
            _kv("Database", database_status),
            _kv("Redis", redis_status),
            _kv("Telegram", telegram_status),
            _kv("Exchange", exchange_status),
            _kv("WebSocket", websocket_status),
            _kv("Live Prices", live_prices_status),
            _kv("Tracked Symbols", tracked_symbols_count),
            _kv("Open Trades", open_trades_count),
            _kv("CPU Usage", f"{cpu_usage:.2f}%"),
            _kv("RAM Usage", f"{ram_usage:.2f}MB"),
            _kv("Heartbeat", heartbeat_status),
            _kv("Last Tick", _fmt_ts(last_tick_time)),
            _kv("Last Candle", _fmt_ts(last_candle_time)),
            _kv("Reconnect Count", reconnect_count),
            _kv("Restart Count", restart_count),
            "╚" + "═" * 53 + "╝",
        ])
        _json_event("system_dashboard_update", {
            "trademonitor_status": trademonitor_status, "ai_engine_status": ai_engine_status, "decision_engine_status": decision_engine_status,
            "risk_engine_status": risk_engine_status, "database_status": database_status, "redis_status": redis_status,
            "telegram_status": telegram_status, "exchange_status": exchange_status, "websocket_status": websocket_status,
            "live_prices_status": live_prices_status, "tracked_symbols_count": tracked_symbols_count,
            "open_trades_count": open_trades_count, "cpu_usage": cpu_usage, "ram_usage": ram_usage,
            "heartbeat_status": heartbeat_status, "last_tick_time": last_tick_time, "last_candle_time": last_candle_time,
            "reconnect_count": reconnect_count, "restart_count": restart_count
        })

    def final_validation_report(self, results: Dict[str, bool]):
        all_ok = all(results.values())
        lines = [
            "",
            "╔" + "═" * 53 + "╗",
            "║  ========== FINAL VALIDATION REPORT ==========".ljust(54) + "║",
            "╠" + "═" * 53 + "╣",
        ]
        for check, status in results.items():
            lines.append(f"║  {_icon(status)} {check}".ljust(54) + "║")
        lines.append("╠" + "═" * 53 + "╣")
        status_msg = "ALL CHECKS PASSED" if all_ok else "FAILED CHECKS"
        lines.append(f"║  SYSTEM STATUS: {status_msg}".ljust(54) + "║")
        lines.append("╚" + "═" * 53 + "╝")
        info(lines)
        _json_event("final_validation_report", {
            "results": results, "all_ok": all_ok
        })

    def config_dump(self, config_module):
        """Dump non-secret config values."""
        lines = [_divider("CONFIGURATION")]
        for attr in dir(config_module):
            if attr.startswith("_") or "PASSWORD" in attr or "SECRET" in attr or "TOKEN" in attr:
                continue
            val = getattr(config_module, attr, None)
            if val is not None and not callable(val):
                lines.append(f"  {attr:24s} {val}")
        lines.append(_SEP55)
        info(lines)

    # ══════════════════════════════════════════════════════════════
    # 2. PRICE STREAM (NORMAL + TRACE)
    # ══════════════════════════════════════════════════════════════

    def price_tick(self, symbol: str, price: float, bid: float = None,
                   ask: float = None, volume_24h: float = None,
                   high_24h: float = None, low_24h: float = None,
                   candle_close: float = None, spread: float = None):
        """Log a live price tick.

        NORMAL: compact 1-line summary per symbol every 60s.
        TRACE:  full box with bid/ask/spread/24h stats every tick.
        """
        prev = self._price_cache.get(symbol)
        self._price_cache[symbol] = price
        now = time.time()
        # NOTE: save last_seen BEFORE updating so delay detection works
        last_seen = self._price_last_seen.get(symbol, 0)
        self._price_last_seen[symbol] = now
        self._price_last_ts[symbol] = now

        _json_event("price_tick", {
            "s": symbol, "p": price, "prev": prev,
            "bid": bid, "ask": ask, "v24": volume_24h,
        })

        # NORMAL: per-symbol compact summary every 60s + first tick always
        ts_key = f"_price_summary_{symbol}"
        last_summary = getattr(self, ts_key, 0)
        if prev is None or now - last_summary >= 60:
            setattr(self, ts_key, now)
            chg = (price - prev) if prev else 0
            chg_str = f"  Δ {chg:+.4f}" if prev else "  (first tick)"
            _log(f"  [LIVE] {symbol}: {price} {chg_str}  {_now_iso()}")

        # TRACE: full price stream box
        if is_trace():
            chg = (price - prev) if prev else 0
            chg_pct = ((price / prev) - 1) * 100 if prev else 0
            info([
                _divider("PRICE STREAM"),
                f"  Symbol:        {symbol}",
                f"  Current Price: {_fmt_price(price)}",
                f"  Previous:      {_fmt_price(prev)}" if prev else f"  Previous:      N/A (first tick)",
                f"  Change:        {_fmt_price(chg)} ({_fmt_pct(chg_pct)})",
                f"  Bid:           {_fmt_price(bid)}" if bid is not None else "",
                f"  Ask:           {_fmt_price(ask)}" if ask is not None else "",
                f"  Spread:        {spread:.8f}" if spread is not None else "",
                f"  24h High:      {_fmt_price(high_24h)}" if high_24h is not None else "",
                f"  24h Low:       {_fmt_price(low_24h)}" if low_24h is not None else "",
                f"  Volume:        {volume_24h:.0f}" if volume_24h is not None else "",
                f"  Candle Close:  {_fmt_price(candle_close)}" if candle_close is not None else "",
                f"  Last Update:   {_now_iso()}",
                _SEP55,
            ])

        # Price delay detection — use last_seen from BEFORE this tick
        if last_seen > 0 and now - last_seen > 60:
            info([
                _divider(f"{_ICON_WARN} PRICE DELAY DETECTED"),
                f"  Symbol:          {symbol}",
                f"  Last update:     {_fmt_ts(last_seen)}",
                f"  Delay:           {now - last_seen:.1f}s",
                f"  Expected:        ≤1s",
                f"  Action:          WebSocket may be stale — will auto-reconnect",
                _SEP55,
            ])

    def price_summary(self, symbol: str, price: float):
        """Periodic price summary at NORMAL level."""
        now = time.time()
        if now - self._last_price_diag < 60:
            return
        self._last_price_diag = now

        prev = self._price_cache.get(symbol)
        if prev and prev != price:
            info([f"  [PRICE] {symbol}: {price} (Δ {price-prev:+.4f})"])

    # ══════════════════════════════════════════════════════════════
    # 3. CANDLE DATA (DEBUG)
    # ══════════════════════════════════════════════════════════════

    def candle_received(self, symbol: str, timeframe: str, open_p: float,
                        high: float, low: float, close_p: float, volume: float,
                        timestamp, source: str = "", latency_ms: float = 0):
        if not is_debug():
            return
        info([
            _divider(f"CANDLE {symbol} {timeframe}"),
            f"  Open:     {_fmt_price(open_p)}",
            f"  High:     {_fmt_price(high)}",
            f"  Low:      {_fmt_price(low)}",
            f"  Close:    {_fmt_price(close_p)}",
            f"  Volume:   {volume:.2f}",
            f"  Time:     {_fmt_ts(timestamp)}",
            f"  Source:   {source}",
            f"  Latency:  {latency_ms:.1f}ms",
            _SEP55,
        ])
        _json_event("candle_received", {
            "s": symbol, "tf": timeframe, "o": open_p, "h": high, "l": low,
            "c": close_p, "v": volume, "ts": timestamp, "src": source,
            "lat": latency_ms,
        })

    # ══════════════════════════════════════════════════════════════
    # 4. STRATEGY & DECISION (DEBUG)
    # ══════════════════════════════════════════════════════════════

    def decision_report(self, symbol: str, verdict: str, confidence: float,
                        probability: float, quality: float, risk_pct: float,
                        rr: float, conditions: List[Dict[str, Any]],
                        reasons: str = ""):
        if not is_debug():
            return
        lines = [
            _divider(f"DECISION REPORT — {symbol}"),
            f"  Verdict:     {verdict}",
            f"  Confidence:  {confidence:.2f}%",
            f"  Probability: {probability:.2f}%",
            f"  Quality:     {quality:.2f}%",
            f"  Risk:        {risk_pct:.2f}%",
            f"  RR:          {rr:.2f}",
            _divider("CONDITIONS"),
        ]
        for cond in conditions:
            passed = cond.get("passed", False)
            lines.append(f"  {_icon(passed)} {cond.get('name')}: {cond.get('reason', '')}")
        if reasons:
            lines.append(_divider("REASONS"))
            lines.append(f"  {reasons}")
        lines.append(_SEP55)
        info(lines)
        _json_event("decision", {
            "s": symbol, "verdict": verdict, "confidence": confidence,
            "probability": probability, "quality": quality, "risk": risk_pct,
            "rr": rr, "conditions": {c["name"]: c["passed"] for c in conditions},
            "reasons": reasons,
        })

    def signal_report(self, symbol: str, signal_type: str, price: float,
                      reason: str, passed: bool):
        if not is_debug():
            return
        info([
            _divider(f"SIGNAL — {symbol}"),
            f"  Type:    {signal_type}",
            f"  Price:   {_fmt_price(price)}",
            f"  Result:  {'PASSED' if passed else 'FAILED'}  {_icon(passed)}",
            f"  Reason:  {reason}",
            _SEP55,
        ])

    # ══════════════════════════════════════════════════════════════
    # 5. TRADE LIFECYCLE (NORMAL)
    # ══════════════════════════════════════════════════════════════

    def trade_opened(self, trade_id: int, symbol: str, direction: str,
                     entry: float, sl: float, tp: float, risk_pct: float,
                     capital: float, strategy: str = "SMC"):
        info([
            "",
            "╔" + "═" * 53 + "╗",
            "║  TRADE OPENED".ljust(54) + "║",
            "╠" + "═" * 53 + "╣",
            f"║  Signal ID:   #{trade_id}".ljust(54) + "║",
            f"║  Symbol:      {symbol}".ljust(54) + "║",
            f"║  Direction:   {direction}".ljust(54) + "║",
            f"║  Entry:       {_fmt_price(entry, 8)}".ljust(54) + "║",
            f"║  Stop Loss:   {_fmt_price(sl, 8)}".ljust(54) + "║",
            f"║  Take Profit: {_fmt_price(tp, 8)}".ljust(54) + "║",
            f"║  Risk:        {risk_pct:.2f}%".ljust(54) + "║",
            f"║  Capital:     {capital:.2f} USDT".ljust(54) + "║",
            f"║  Strategy:    {strategy}".ljust(54) + "║",
            "╚" + "═" * 53 + "╝",
        ])
        _json_event("trade_opened", {
            "id": trade_id, "s": symbol, "dir": direction, "entry": entry,
            "sl": sl, "tp": tp, "risk": risk_pct, "capital": capital,
        })

    def trade_monitor(self, trade_id: int, symbol: str, current_price: float,
                      entry: float, sl: float, tp: float, unrealized_pnl: float):
        """During-trade monitoring at DEBUG level."""
        if not is_debug():
            return
        dist_sl = abs(current_price - sl)
        dist_tp = abs(tp - current_price)
        info([
            _divider(f"TRADE MONITOR #{trade_id} — {symbol}"),
            f"  Current Price:  {_fmt_price(current_price, 8)}",
            f"  Unrealized PnL: {unrealized_pnl:+.4f}",
            f"  Distance SL:    {_fmt_price(dist_sl, 8)}",
            f"  Distance TP:    {_fmt_price(dist_tp, 8)}",
            _SEP55,
        ])

    def trade_closed(self, trade_id: int, symbol: str, direction: str,
                     entry: float, exit_price: float, pnl: float,
                     pnl_pct: float, reason: str, duration_s: float = 0):
        emoji = "🟢" if pnl > 0 else "🔴"
        info([
            "",
            "╔" + "═" * 53 + "╗",
            "║  TRADE CLOSED".ljust(54) + "║",
            "╠" + "═" * 53 + "╣",
            f"║  Signal ID:   #{trade_id}".ljust(54) + "║",
            f"║  Symbol:      {symbol}".ljust(54) + "║",
            f"║  Direction:   {direction}".ljust(54) + "║",
            f"║  Entry:       {_fmt_price(entry, 8)}".ljust(54) + "║",
            f"║  Exit:        {_fmt_price(exit_price, 8)}".ljust(54) + "║",
            f"║  Result:      {emoji} {pnl:+.2f} USDT ({pnl_pct:+.3f}%)".ljust(54) + "║",
            f"║  Reason:      {reason}".ljust(54) + "║",
            f"║  Duration:    {duration_s:.0f}s".ljust(54) + "║" if duration_s else "",
            "╚" + "═" * 53 + "╝",
        ])
        _json_event("trade_closed", {
            "id": trade_id, "s": symbol, "dir": direction,
            "entry": entry, "exit": exit_price, "pnl": pnl,
            "pnl_pct": pnl_pct, "reason": reason,
        })

    # ══════════════════════════════════════════════════════════════
    # 7. FULL ERROR DIAGNOSTICS (ALWAYS)
    # ══════════════════════════════════════════════════════════════

    def error_full(self, component: str, function: str, error_type: str,
                   message: str, input_data: Any = None, state: Any = None,
                   cause: str = "", fix: str = ""):
        tb = traceback.format_exc()
        lines = [
            "",
            "╔" + "═" * 53 + "╗",
            "║  ❌  ERROR REPORT".ljust(54) + "║",
            "╠" + "═" * 53 + "╣",
            f"║  Time:        {_now_iso()}".ljust(54) + "║",
            f"║  Component:   {component}".ljust(54) + "║",
            f"║  Function:    {function}".ljust(54) + "║",
            f"║  Error Type:  {error_type}".ljust(54) + "║",
            f"║  Message:     {message}".ljust(54) + "║",
        ]
        if input_data is not None:
            lines.append(f"║  Input:       {str(input_data)[:150]}".ljust(54) + "║")
        if state is not None:
            lines.append(f"║  State:       {str(state)[:150]}".ljust(54) + "║")
        if cause:
            lines.append(f"║  Cause:       {cause}".ljust(54) + "║")
        if fix:
            lines.append(f"║  Fix:         {fix}".ljust(54) + "║")
        lines.append("╠" + "═" * 53 + "╣")
        if tb and tb != "NoneType: None":
            lines.append(f"║  Stack Trace:".ljust(54) + "║")
            for line in tb.strip().split("\n")[-8:]:
                lines.append(f"║    {line[:50]}".ljust(54) + "║")
        lines.append("╚" + "═" * 53 + "╝")
        info(lines)
        _json_event("error", {
            "component": component, "function": function,
            "error_type": error_type, "message": message,
            "cause": cause, "fix": fix,
        })

    # ══════════════════════════════════════════════════════════════
    # 8. CONNECTION MONITORING (NORMAL + DEBUG)
    # ══════════════════════════════════════════════════════════════

    def binance_ws_status(self, connected: bool, latency_ms: float = 0,
                          symbols: int = 0, msg_count: int = 0,
                          api_limit_ok: bool = True):
        self._ws_msg_count += msg_count
        if not is_debug():
            # Normal: only log status changes
            return
        info([
            _divider("BINANCE MONITOR"),
            f"  WebSocket:    {'CONNECTED' if connected else 'DISCONNECTED'}  {_icon(connected)}",
            f"  Latency:      {latency_ms:.0f}ms",
            f"  Symbols:      {symbols}",
            f"  Msg/min:      ~{msg_count * 12:.0f}",
            f"  API Limit:    {'OK' if api_limit_ok else 'WARNING'}  {_icon(api_limit_ok)}",
            _SEP55,
        ])

    def ws_reconnect(self, attempt: int, reason: str = ""):
        msg = f"  {_ICON_WARN} [WS] Reconnect #{attempt}: {reason}" if reason else f"  {_ICON_WARN} [WS] Reconnect #{attempt}"
        info([msg])

    def db_query(self, operation: str, table: str, result: str = "SUCCESS",
                 elapsed_ms: float = 0, error: str = ""):
        if not is_trace():
            return
        ok = result == "SUCCESS"
        info([
            _divider(f"DATABASE QUERY — {operation}"),
            f"  Table:    {table}",
            f"  Result:   {result}  {_icon(ok)}",
            f"  Time:     {elapsed_ms:.1f}ms",
            *([f"  Error:    {error}"] if error else []),
            _SEP55,
        ])

    def cache_op(self, op: str, key: str, status: str = "OK",
                 age_s: float = 0):
        if not is_trace():
            return
        info([
            _divider("CACHE STATUS"),
            f"  Key:      {key}",
            f"  Age:      {age_s:.0f}s",
            f"  Status:   {status}  {_icon(status == 'VALID')}",
            _SEP55,
        ])

    def api_rest_call(self, endpoint: str, elapsed_ms: float = 0, ok: bool = True):
        """Track REST API calls."""
        self._api_rest_count += 1
        self._last_rest_call = time.time()
        if not is_trace():
            return
        info([
            f"  [API] {'GET' if 'fetch' in endpoint else 'POST'} {endpoint} "
            f"→ {elapsed_ms:.0f}ms  {_icon(ok)}",
        ])

    # ══════════════════════════════════════════════════════════════
    # 9. PERFORMANCE SUMMARY (DEBUG)
    # ══════════════════════════════════════════════════════════════

    def perf_summary(self, measurements: Dict[str, float]):
        if not is_debug():
            return
        total = sum(measurements.values())
        lines = [_divider("PERFORMANCE"),]
        for label, elapsed in measurements.items():
            lines.append(f"  {label:30s} {elapsed:.4f}s")
        lines.append(f"  {'─'*40}")
        lines.append(f"  {'TOTAL':30s} {total:.4f}s")
        lines.append(_SEP55)
        info(lines)

    # ══════════════════════════════════════════════════════════════
    # 10. SYSTEM SNAPSHOT (NORMAL — every 5 minutes)
    # ══════════════════════════════════════════════════════════════

    def system_snapshot(self, symbol: str = "", price: float = 0,
                        indicators: Dict = None, smc: Dict = None,
                        strategies: Dict = None, verdict: str = "",
                        confidence: float = 0, reason: str = "",
                        open_trades: int = 0, api_calls: int = 0,
                        uptime: float = 0):
        """Periodic full snapshot of system state."""
        now = time.time()
        if now - self._last_snapshot < 300:  # every 5 minutes
            return
        self._last_snapshot = now

        try:
            import psutil
            mem = psutil.Process().memory_info().rss / 1024 / 1024
            cpu = psutil.cpu_percent(interval=0.1)
        except (ImportError, Exception):
            try:
                # Linux /proc fallback — works on Render without extra deps
                with open("/proc/self/status") as f:
                    for line in f:
                        if line.startswith("VmRSS:"):
                            mem = int(line.split()[1]) / 1024.0  # kB → MB
                            break
                    else:
                        mem = 0
                cpu = 0.0
            except Exception:
                mem = 0
                cpu = 0

        lines = [
            "",
            "╔" + "═" * 53 + "╗",
            "║  " + "SYSTEM SNAPSHOT".center(51) + "║",
            "╠" + "═" * 53 + "╣",
            f"║  {_kv('Time', _now_iso())}".ljust(54) + "║",
            f"║  {_kv('Uptime', f'{uptime:.0f}s')}".ljust(54) + "║",
            f"║  {_kv('CPU', f'{cpu:.0f}%')}".ljust(54) + "║",
            f"║  {_kv('Memory', f'{mem:.0f}MB')}".ljust(54) + "║",
            f"║  {_kv('Open Trades', open_trades)}".ljust(54) + "║",
            f"║  {_kv('API Calls', api_calls)}".ljust(54) + "║",
            f"║  {_kv('WS Connected', self._ws_reconnects == 0)}".ljust(54) + "║" if not is_debug() else "",
            "╠" + "═" * 53 + "╣",
        ]
        if symbol:
            lines.append(f"║  MARKET DATA".ljust(54) + "║")
            lines.append(f"║  {_kv('Symbol', symbol)}".ljust(54) + "║")
            lines.append(f"║  {_kv('Price', _fmt_price(price))}".ljust(54) + "║")
        if verdict:
            lines.append("╠" + "═" * 53 + "╣")
            lines.append(f"║  {_kv('Decision', f'{verdict} ({confidence:.0f}%)')}".ljust(54) + "║")
            lines.append(f"║  {_kv('Reason', reason[:40])}".ljust(54) + "║")
        lines.append("╚" + "═" * 53 + "╝")
        info(lines)

    def event_log(self, module: str, function: str, detail: str = "",
                  elapsed_ms: float = 0, status: str = "OK"):
        """Internal engine event at DEBUG level."""
        if not is_debug():
            return
        info([
            _divider("ENGINE EVENT"),
            f"  Module:      {module}",
            f"  Function:    {function}",
            f"  Status:      {status}  {_icon(status == 'OK')}",
            f"  Time:        {elapsed_ms:.1f}ms",
            *([f"  Detail:      {detail}"] if detail else []),
            _SEP55,
        ])

    def timer(self, label: str) -> PerfTimer:
        return PerfTimer(label, obs=self)

    @property
    def api_rest_count(self) -> int:
        return self._api_rest_count

    @property
    def ws_reconnects(self) -> int:
        return self._ws_reconnects

    def inc_ws_reconnects(self):
        self._ws_reconnects += 1


# ═══════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════

_obs: Optional[_Obs] = None

class Obs:
    """Public API — always use Obs.get() to access the singleton."""

    @staticmethod
    def get() -> _Obs:
        global _obs
        if _obs is None:
            _obs = _Obs()
        return _obs

    # Convenience wrappers for common patterns

    @staticmethod
    def startup_banner():
        Obs.get().startup_banner()

    @staticmethod
    def startup_report(components: Dict[str, bool]):
        Obs.get().startup_report(components)

    @staticmethod
    def price_tick(symbol: str, price: float, **kwargs):
        Obs.get().price_tick(symbol, price, **kwargs)

    @staticmethod
    def candle_received(symbol: str, timeframe: str, open_p: float,
                        high: float, low: float, close_p: float, volume: float,
                        timestamp, **kwargs):
        Obs.get().candle_received(symbol, timeframe, open_p, high, low,
                                  close_p, volume, timestamp, **kwargs)

    @staticmethod
    def decision_report(symbol: str, verdict: str, confidence: float,
                        probability: float, quality: float, risk_pct: float,
                        rr: float, conditions: List[Dict[str, Any]],
                        reasons: str = ""):
        Obs.get().decision_report(symbol, verdict, confidence, probability,
                                  quality, risk_pct, rr, conditions, reasons)

    @staticmethod
    def trade_opened(*args, **kwargs):
        Obs.get().trade_opened(*args, **kwargs)

    @staticmethod
    def trade_monitor(*args, **kwargs):
        Obs.get().trade_monitor(*args, **kwargs)

    @staticmethod
    def trade_closed(*args, **kwargs):
        Obs.get().trade_closed(*args, **kwargs)

    @staticmethod
    def error_full(*args, **kwargs):
        Obs.get().error_full(*args, **kwargs)

    @staticmethod
    def binance_ws_status(*args, **kwargs):
        Obs.get().binance_ws_status(*args, **kwargs)

    @staticmethod
    def ws_reconnect(*args, **kwargs):
        Obs.get().ws_reconnect(*args, **kwargs)

    @staticmethod
    def db_query(*args, **kwargs):
        Obs.get().db_query(*args, **kwargs)

    @staticmethod
    def cache_op(*args, **kwargs):
        Obs.get().cache_op(*args, **kwargs)

    @staticmethod
    def api_rest_call(*args, **kwargs):
        Obs.get().api_rest_call(*args, **kwargs)

    @staticmethod
    def perf_summary(*args, **kwargs):
        Obs.get().perf_summary(*args, **kwargs)

    @staticmethod
    def system_snapshot(*args, **kwargs):
        Obs.get().system_snapshot(*args, **kwargs)

    @staticmethod
    def event_log(*args, **kwargs):
        Obs.get().event_log(*args, **kwargs)

    @staticmethod
    def timer(label: str) -> PerfTimer:
        return Obs.get().timer(label)

    @staticmethod
    def inc_ws_reconnects():
        Obs.get().inc_ws_reconnects()

    @property
    def api_rest_count(self) -> int:
        return self._api_rest_count

    @property
    def ws_reconnects(self) -> int:
        return self._ws_reconnects

    @staticmethod
    def signal_report(*args, **kwargs):
        Obs.get().signal_report(*args, **kwargs)

    @staticmethod
    def startup_step(*args, **kwargs):
        Obs.get().startup_step(*args, **kwargs)

    @staticmethod
    def constructor_log(*args, **kwargs):
        Obs.get().constructor_log(*args, **kwargs)

    @staticmethod
    def task_status_report(*args, **kwargs):
        Obs.get().task_status_report(*args, **kwargs)

    @staticmethod
    def task_crash_report(*args, **kwargs):
        Obs.get().task_crash_report(*args, **kwargs)

    @staticmethod
    def heartbeat_update(*args, **kwargs):
        Obs.get().heartbeat_update(*args, **kwargs)

    @staticmethod
    def trademonitor_loop_log(*args, **kwargs):
        Obs.get().trademonitor_loop_log(*args, **kwargs)

    @staticmethod
    def websocket_event(*args, **kwargs):
        Obs.get().websocket_event(*args, **kwargs)

    @staticmethod
    def live_price_tick_full(*args, **kwargs):
        Obs.get().live_price_tick_full(*args, **kwargs)

    @staticmethod
    def db_query_full(*args, **kwargs):
        Obs.get().db_query_full(*args, **kwargs)

    @staticmethod
    def db_tracked_coins_load(*args, **kwargs):
        Obs.get().db_tracked_coins_load(*args, **kwargs)

    @staticmethod
    def strategy_execution(*args, **kwargs):
        Obs.get().strategy_execution(*args, **kwargs)

    @staticmethod
    def indicator_calculation(*args, **kwargs):
        Obs.get().indicator_calculation(*args, **kwargs)

    @staticmethod
    def decision_rule_evaluation(*args, **kwargs):
        Obs.get().decision_rule_evaluation(*args, **kwargs)

    @staticmethod
    def trademonitor_crash_report(*args, **kwargs):
        Obs.get().trademonitor_crash_report(*args, **kwargs)

    @staticmethod
    def restart_event(*args, **kwargs):
        Obs.get().restart_event(*args, **kwargs)

    @staticmethod
    def system_dashboard_update(*args, **kwargs):
        Obs.get().system_dashboard_update(*args, **kwargs)

    @staticmethod
    def final_validation_report(*args, **kwargs):
        Obs.get().final_validation_report(*args, **kwargs)
