"""
Comprehensive system health diagnostics and observability framework.

Two logging levels via DEBUG_MODE env var:
  - NORMAL  (DEBUG_MODE=false): important events only
  - DEBUG   (DEBUG_MODE=true):  full internal state, data flow, decisions

Usage::

    from Core.diagnostics import Diagnostics, set_debug_mode

    set_debug_mode(True)          # or read from env
    diag = Diagnostics()

    # Startup
    diag.startup_report(...)

    # Per-analysis
    diag.market_analysis_summary(...)
    diag.decision_checklist(...)

    # Periodic
    diag.websocket_stats(...)
    diag.data_pipeline_health(...)
"""

import os
import sys
import logging
import time
import platform
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("CT_Diagnostics")

# ── Global debug toggle ─────────────────────────────────────────────
try:
    import config
    _DEBUG_MODE = getattr(config, "DEBUG_MODE", False)
except ImportError:
    _DEBUG_MODE = False


def set_debug_mode(enabled: bool):
    global _DEBUG_MODE
    _DEBUG_MODE = enabled


def is_debug() -> bool:
    return _DEBUG_MODE


# ── Utility ─────────────────────────────────────────────────────────

def _fmt_ts(ts: Optional[float]) -> str:
    if ts is None:
        return "N/A"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M:%S")


def _age_seconds(ts: Optional[float]) -> str:
    if ts is None:
        return "N/A"
    return f"{time.time() - ts:.1f}s ago"


def _icon(ok: bool) -> str:
    return "✅" if ok else "❌"


class Diagnostics:
    """Central diagnostics logger for CT trading system."""

    def __init__(self, started_at: Optional[float] = None):
        self.started_at = started_at or time.time()

    # ═══════════════════════════════════════════════════════════════
    # 1. STARTUP REPORT
    # ═══════════════════════════════════════════════════════════════

    def startup_banner(self):
        logger.info("=" * 55)
        logger.info("   CT INSTITUTIONAL TRADING SYSTEM  V4.0")
        logger.info("=" * 55)
        logger.info("  Environment : %s", "Render" if os.environ.get("RENDER") else "local")
        logger.info("  Python      : %s", platform.python_version())
        logger.info("  Process ID  : %d", os.getpid())
        logger.info("  Started at  : %s", _fmt_ts(self.started_at))
        logger.info("  DEBUG_MODE  : %s", "ON 🔍" if _DEBUG_MODE else "OFF")
        logger.info("=" * 55)

    def startup_report(self, components: Dict[str, bool]):
        """Print a compact startup health grid.

        Args:
            components: dict of name -> bool (True = healthy)
        """
        logger.info("")
        logger.info("========== CT SYSTEM STARTUP REPORT ==========")
        for name, ok in components.items():
            logger.info("  %-22s %s", name, _icon(ok))
        all_ok = all(components.values())
        logger.info("  %-22s %s", "OVERALL", _icon(all_ok))
        logger.info("  System Ready" if all_ok else "  ⚠️  Some components failed!")
        logger.info("==============================================")

    # ═══════════════════════════════════════════════════════════════
    # 2. CONFIG DIAGNOSTICS
    # ═══════════════════════════════════════════════════════════════

    def config_status(
        self,
        db_ok: bool,
        redis_ok: bool,
        telegram_ok: bool,
        ws_ok: bool,
        env_ok: bool,
    ):
        logger.info("")
        logger.info("  CONFIG STATUS")
        logger.info("  %-22s %s", "Database", _icon(db_ok))
        logger.info("  %-22s %s", "Redis", _icon(redis_ok))
        logger.info("  %-22s %s", "Telegram", _icon(telegram_ok))
        logger.info("  %-22s %s", "Binance WS", _icon(ws_ok))
        logger.info("  %-22s %s", "Environment", _icon(env_ok))

    # ═══════════════════════════════════════════════════════════════
    # 3. DATABASE DIAGNOSTICS
    # ═══════════════════════════════════════════════════════════════

    def database_health(
        self,
        connected: bool,
        pool_active: int = 0,
        pool_total: int = 0,
        tables: Optional[Dict[str, bool]] = None,
        last_query_ms: float = 0,
    ):
        logger.info("")
        logger.info("  DATABASE HEALTH")
        logger.info("  Connection   %s", _icon(connected))
        logger.info("  Pool         %d/%d active", pool_active, pool_total)
        if tables:
            for name, ok in tables.items():
                logger.info("  %-12s table %s", name, _icon(ok))
        logger.info("  Last query   %dms", int(last_query_ms))

    # ═══════════════════════════════════════════════════════════════
    # 4. DATA PIPELINE
    # ═══════════════════════════════════════════════════════════════

    def data_pipeline_health(
        self,
        ws_status: str = "Unknown",
        ws_last_tick: Optional[float] = None,
        ws_latency_ms: float = 0,
        cache_candles: int = 0,
        cache_last_update: Optional[float] = None,
        indicators_ok: bool = False,
        decision_input_ok: bool = False,
    ):
        logger.info("")
        logger.info("  DATA PIPELINE")
        logger.info("")
        logger.info("  Binance WebSocket")
        logger.info("    Status:     %s  %s", ws_status, _icon(ws_status == "Connected"))
        logger.info("    Last tick:  %s", _fmt_ts(ws_last_tick))
        logger.info("    Latency:    %.0fms", ws_latency_ms)
        logger.info("")
        logger.info("  Cache (Redis)")
        logger.info("    Candles:    %d", cache_candles)
        logger.info("    Last update:%s  (%s)", _fmt_ts(cache_last_update), _age_seconds(cache_last_update))
        logger.info("")
        logger.info("  Indicators    %s", _icon(indicators_ok))
        logger.info("  Decision Engine")
        logger.info("    Input:      %s", _icon(decision_input_ok))

    # ═══════════════════════════════════════════════════════════════
    # 5. WEB SOCKET STATS
    # ═══════════════════════════════════════════════════════════════

    def websocket_stats(
        self,
        connected: bool,
        symbols_count: int = 0,
        messages_per_min: float = 0,
        latency_ms: float = 0,
        last_message: str = "",
        reconnect_attempts: int = 0,
    ):
        logger.info("")
        logger.info("  WEBSOCKET")
        logger.info("  Status:       %s  %s", "Connected" if connected else "Disconnected", _icon(connected))
        logger.info("  Symbols:      %d", symbols_count)
        logger.info("  Messages/min: %.0f", messages_per_min)
        logger.info("  Latency:      %.0fms", latency_ms)
        logger.info("  Last message: %s", last_message or "N/A")
        logger.info("  Reconnects:   %d", reconnect_attempts)

    # ═══════════════════════════════════════════════════════════════
    # 6. MARKET ANALYSIS (per-cycle)
    # ═══════════════════════════════════════════════════════════════

    def market_analysis_summary(self, data: Dict[str, Any]):
        """Print a per-symbol analysis summary.

        Called from AIEngine.analyze_and_trade().
        """
        if not _DEBUG_MODE:
            return

        logger.info("")
        logger.info("  ── MARKET ANALYSIS ──")
        logger.info("  Symbol:      %s", data.get("symbol", "?"))
        logger.info("  Timeframe:   %s", data.get("timeframe", "?"))
        logger.info("  Current Price:%s", data.get("price", "?"))
        logger.info("  Candle Time: %s", data.get("candle_time", "?"))
        logger.info("  Candle Count:%s", data.get("candle_count", "?"))
        logger.info("  Trend:       %s", data.get("trend", "?"))
        logger.info("  HTF Align:   %s", data.get("htf_align", "?"))
        logger.info("")
        logger.info("  Indicators:")
        logger.info("    RSI:       %s", data.get("rsi", "?"))
        logger.info("    MACD:      %s", data.get("macd", "?"))
        logger.info("    EMA:       %s", data.get("ema", "?"))
        logger.info("    ATR:       %s", data.get("atr", "?"))
        logger.info("    Volume:    %s", data.get("volume", "?"))
        logger.info("")
        logger.info("  Smart Money:")
        logger.info("    BOS:       %s", data.get("smc_bos", "?"))
        logger.info("    CHoCH:     %s", data.get("smc_choch", "?"))
        logger.info("    FVG:       %s", data.get("smc_fvg", "?"))
        logger.info("    Liq Sweep: %s", data.get("smc_liq_sweep", "?"))
        logger.info("    OrderBlock:%s", data.get("smc_ob", "?"))
        logger.info("")
        logger.info("  Strategies:")
        logger.info("    Breakout:  %s", data.get("strat_breakout", "?"))
        logger.info("    Momentum:  %s", data.get("strat_momentum", "?"))
        logger.info("    MeanRev:   %s", data.get("strat_meanrev", "?"))
        logger.info("")
        logger.info("  Score:       %s", data.get("score", "?"))
        logger.info("  Confidence:  %s", data.get("confidence", "?"))
        logger.info("  Risk:        %s", data.get("risk", "?"))
        logger.info("  Decision:    %s", data.get("verdict", "?"))
        logger.info("  Reason:      %s", data.get("reason", "?"))

    # ═══════════════════════════════════════════════════════════════
    # 7. DECISION CHECKLIST
    # ═══════════════════════════════════════════════════════════════

    def decision_checklist(self, checklist: List[Dict[str, Any]]):
        """Print every condition that led to BUY/SKIP.

        Each item: {name, current, required, passed, module}
        """
        logger.info("")
        logger.info("  DECISION CHECKLIST")
        logger.info("  %-24s %12s %12s %6s", "Condition", "Current", "Required", "PASS")
        logger.info("  " + "-" * 56)

        passed_all = True
        for c in checklist:
            icon = _icon(c.get("passed", False))
            logger.info(
                "  %-24s %12s %12s  %s",
                c.get("name", "?"),
                str(c.get("current", "?")),
                str(c.get("required", "?")),
                icon,
            )
            if not c.get("passed", False):
                passed_all = False

        logger.info("  " + "-" * 56)
        logger.info("  FINAL RESULT: %s", "BUY/SELL" if passed_all else "SKIP")

        # Show exact failed conditions
        failed = [c for c in checklist if not c.get("passed", False)]
        if failed:
            logger.info("")
            logger.info("  FAILED CONDITIONS:")
            for c in failed:
                logger.info(
                    "    • %s  (current=%s, required=%s, module=%s)",
                    c.get("name", "?"),
                    c.get("current", "?"),
                    c.get("required", "?"),
                    c.get("module", "?"),
                )

    # ═══════════════════════════════════════════════════════════════
    # 8. ERROR TRACKING
    # ═══════════════════════════════════════════════════════════════

    def error_report(
        self,
        module: str,
        function: str,
        error_type: str,
        message: str,
        stack_trace: str = "",
        recovery_action: str = "",
    ):
        logger.error("")
        logger.error("  ERROR REPORT")
        logger.error("  Timestamp:  %s", datetime.now(timezone.utc).isoformat())
        logger.error("  Module:     %s", module)
        logger.error("  Function:   %s", function)
        logger.error("  Error:      %s", error_type)
        logger.error("  Message:    %s", message)
        if stack_trace:
            logger.error("  Stack:\n%s", stack_trace)
        if recovery_action:
            logger.error("  Recovery:   %s", recovery_action)

    # ═══════════════════════════════════════════════════════════════
    # 9. PERIODIC SYSTEM HEALTH
    # ═══════════════════════════════════════════════════════════════

    def periodic_health(
        self,
        uptime_seconds: float = 0,
        api_calls: int = 0,
        open_trades: int = 0,
        tracked_coins: int = 0,
        memory_mb: float = 0,
    ):
        logger.info("")
        logger.info("  ================ SYSTEM HEALTH CHECK ================")
        logger.info("  Uptime:        %.0fs", uptime_seconds)
        logger.info("  API Calls:     %d", api_calls)
        logger.info("  Open Trades:   %d", open_trades)
        logger.info("  Tracked Coins: %d", tracked_coins)
        logger.info("  Memory:        %.1f MB", memory_mb)
        logger.info("  =====================================================")


# ── Global instance ─────────────────────────────────────────────────
_instance: Optional[Diagnostics] = None


def get_diagnostics() -> Diagnostics:
    global _instance
    if _instance is None:
        _instance = Diagnostics()
    return _instance
