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
    """Print to stdout only — Render captures both stdout and stderr.

    We intentionally do NOT also log via the logging module, because
    basicConfig already emits to stderr which Render also captures,
    producing duplicate lines for every observability event.
    """
    print(msg)


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
            f"  {_kv('Obs Level', _current_level.name, indent=0)}",
            _SEP55,
        ])
        _json_event("startup", {
            "env": os.environ.get("RENDER", "local"),
            "python": platform.python_version(),
            "pid": os.getpid(),
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
        lines.append(f"  {'✅' if all_ok else '❌'} SYSTEM {'READY' if all_ok else 'HAS ISSUES'}")
        lines.append(_SEP55)
        info(lines)

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
        """Log a live price tick. At NORMAL: summary every 60s. At TRACE: every tick."""

        prev = self._price_cache.get(symbol)
        self._price_cache[symbol] = price
        now = time.time()
        self._price_last_ts[symbol] = now
        self._price_last_seen[symbol] = now

        # Always track for JSON
        _json_event("price_tick", {
            "s": symbol, "p": price, "prev": prev,
            "bid": bid, "ask": ask, "v24": volume_24h,
        })

        # TRACE: every tick
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

        # Price delay detection
        last = self._price_last_seen.get(symbol, 0)
        if now - last > 60 and last > 0:
            info([
                _divider(f"{_ICON_WARN} PRICE DELAY DETECTED"),
                f"  Symbol:          {symbol}",
                f"  Last update:     {_fmt_ts(last)}",
                f"  Delay:           {now - last:.1f}s",
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
                        timestamp, source: str = "WebSocket", latency_ms: float = 0,
                        cache_valid: bool = True):
        if not is_debug():
            return
        info([
            _divider(f"CANDLE RECEIVED — {symbol} {timeframe}"),
            f"  Open:      {_fmt_price(open_p, 8)}",
            f"  High:      {_fmt_price(high, 8)}",
            f"  Low:       {_fmt_price(low, 8)}",
            f"  Close:     {_fmt_price(close_p, 8)}",
            f"  Volume:    {volume:.0f}",
            f"  Time:      {_fmt_ts(timestamp)}",
            f"  Source:    {source}",
            f"  Cache:     {'VALID' if cache_valid else 'STALE'}  {_icon(cache_valid)}",
            f"  Latency:   {latency_ms:.0f}ms",
            _SEP55,
        ])

    def market_data_loaded(self, symbol: str, df, df_htf, elapsed: float):
        """Log OHLCV data fetch details."""
        if not is_debug():
            return
        ltf_n = len(df) if hasattr(df, '__len__') else 0
        htf_n = len(df_htf) if hasattr(df_htf, '__len__') else 0
        last_idx = str(df.index[-1]) if hasattr(df, 'index') and len(df) > 0 else "N/A"
        nans = df.isnull().sum().sum() if hasattr(df, 'isnull') else '?'
        info([
            _divider("MARKET DATA LOADED"),
            f"  Symbol:        {symbol}",
            f"  LTF candles:   {ltf_n}  ({last_idx})",
            f"  HTF candles:   {htf_n}",
            f"  Missing:       {nans} NaNs",
            f"  Fetch time:    {elapsed:.4f}s",
            _SEP55,
        ])

    # ══════════════════════════════════════════════════════════════
    # 4. STRATEGY ENGINE TRANSPARENCY (DEBUG)
    # ══════════════════════════════════════════════════════════════

    def strategy_check(self, name: str, checks: List[Dict[str, Any]],
                       score: float, passed: bool, reason: str = ""):
        """Log per-strategy condition check results."""
        if not is_debug():
            return
        lines = [
            _divider(f"STRATEGY: {name}"),
            f"  Checking:",
        ]
        for c in checks:
            s = _icon(c.get("status", False))
            lines.append(f"    {s} {c.get('name', '?'):20s} | "
                        f"Current={c.get('current','?')} | Required={c.get('required','?')}")
        lines.append(f"  Score:   {score:.1f}%")
        lines.append(f"  Result:  {'PASSED' if passed else 'FAILED'}  {_icon(passed)}")
        if reason:
            lines.append(f"  Reason:  {reason}")
        lines.append(_SEP55)
        info(lines)

    # ══════════════════════════════════════════════════════════════
    # 5. DECISION ENGINE — FULL TRANSPARENCY (NORMAL/DEBUG)
    # ══════════════════════════════════════════════════════════════

    def decision_report(self, symbol: str, verdict: str, confidence: float,
                        probability: float, quality: float, risk_pct: float,
                        rr: float, conditions: List[Dict[str, Any]],
                        reasons: str = ""):
        """
        Print the COMPLETE decision report. NEVER just "SKIP".

        conditions: [{name, current, required, passed, module}, ...]
        """
        all_passed = all(c.get("passed", False) for c in conditions)
        emoji = {"BUY": "🚀", "SELL": "🔻"}.get(verdict, "🛑")

        lines = [
            "",
            "╔" + "═" * 53 + "╗",
            f"║  DECISION REPORT — {symbol}".ljust(54) + "║",
            "╠" + "═" * 53 + "╣",
            f"║  Final Decision:  {verdict:6s}  {emoji}".ljust(54) + "║",
            f"║  Confidence:      {confidence:.1f}%".ljust(54) + "║",
            f"║  Probability:     {probability:.1f}%".ljust(54) + "║",
            f"║  Quality:         {quality:.1f}/100".ljust(54) + "║",
            f"║  Risk:            {risk_pct:.2f}%".ljust(54) + "║",
            f"║  Reward Ratio:    1:{rr:.1f}".ljust(54) + "║",
            "╠" + "═" * 53 + "╣",
            "║  ALL CONDITIONS:".ljust(54) + "║",
        ]
        for c in conditions:
            s = "PASS" if c["passed"] else "FAIL"
            lines.append(
                f"║    {_icon(c['passed'])} {c['name'][:38]:38s} {s:4s}".ljust(54) + "║"
            )
        lines.append("╠" + "═" * 53 + "╣")

        # Explain exactly why
        if all_passed:
            lines.append(f"║  REASON: All conditions passed.".ljust(54) + "║")
        else:
            lines.append(f"║  REASON: Trade rejected because:".ljust(54) + "║")
            for c in conditions:
                if not c["passed"]:
                    lines.append(
                        f"║    • {c['name']}: {c['current']} vs {c['required']}".ljust(54) + "║"
                    )
            if reasons:
                lines.append(f"║    {reasons}".ljust(54) + "║")
        lines.append("╚" + "═" * 53 + "╝")

        info(lines)
        _json_event("decision", {
            "s": symbol, "verdict": verdict, "confidence": confidence,
            "probability": probability, "quality": quality, "risk": risk_pct,
            "rr": rr, "conditions": {c["name"]: c["passed"] for c in conditions},
        })

    # ══════════════════════════════════════════════════════════════
    # 6. TRADE LIFECYCLE (NORMAL)
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
        info([f"  {_ICON_WARN} [WS] Reconnect #{attempt}: {reason}" if reason else f"  {_ICON_WARN} [WS] Reconnect #{attempt}"])

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
    def trade_closed(*args, **kwargs):
        Obs.get().trade_closed(*args, **kwargs)

    @staticmethod
    def error_full(component: str, function: str, error_type: str,
                   message: str, **kwargs):
        Obs.get().error_full(component, function, error_type, message, **kwargs)

    @staticmethod
    def error(component: str, function: str, exc: Exception, **kwargs):
        Obs.get().error_full(
            component, function, type(exc).__name__, str(exc), **kwargs
        )

    @staticmethod
    def binance_ws_status(*args, **kwargs):
        Obs.get().binance_ws_status(*args, **kwargs)

    @staticmethod
    def ws_reconnect(attempt: int, reason: str = ""):
        Obs.get().ws_reconnect(attempt, reason)

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
    def perf_summary(measurements: Dict[str, float]):
        Obs.get().perf_summary(measurements)

    @staticmethod
    def system_snapshot(**kwargs):
        Obs.get().system_snapshot(**kwargs)

    @staticmethod
    def event_log(module: str, function: str, detail: str = "", **kwargs):
        Obs.get().event_log(module, function, detail=detail, **kwargs)

    @staticmethod
    def timer(label: str) -> PerfTimer:
        return Obs.get().timer(label)

    @staticmethod
    def strategy_check(name: str, checks: List[Dict[str, Any]],
                       score: float, passed: bool, reason: str = ""):
        Obs.get().strategy_check(name, checks, score, passed, reason)

    @staticmethod
    def trade_monitor(trade_id: int, symbol: str, current_price: float,
                      entry: float, sl: float, tp: float, unrealized_pnl: float):
        Obs.get().trade_monitor(trade_id, symbol, current_price, entry,
                                sl, tp, unrealized_pnl)

    @staticmethod
    def market_data_loaded(symbol: str, df, df_htf, elapsed: float):
        Obs.get().market_data_loaded(symbol, df, df_htf, elapsed)

    @staticmethod
    def config_dump(config_module):
        Obs.get().config_dump(config_module)

    @staticmethod
    def price_summary(symbol: str, price: float):
        Obs.get().price_summary(symbol, price)

    @property
    def api_rest_count(self):
        return Obs.get().api_rest_count

    @property
    def ws_reconnects(self):
        return Obs.get().ws_reconnects

    @staticmethod
    def inc_ws_reconnects():
        Obs.get().inc_ws_reconnects()
