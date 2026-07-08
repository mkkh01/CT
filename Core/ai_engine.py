import os
import sys
import asyncio
import logging
import time
import traceback
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import pandas as pd
import numpy as np

from database import AsyncSessionLocal, ShadowTrade, UserConfig
from config import (
    BINANCE_API_KEY, BINANCE_API_SECRET,
    DECISION_CONFIG,
    ADMIN_ID,
)
from Core.redis_client import redis_client
from strategies import InstitutionalStrategies
from Core.utils import safe_create_task, DiagnosticLogger
from Core.observability import Obs, Level, is_level

logger = logging.getLogger("CT_System")


# ══════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════

def _fmt_ts(ts_val) -> str:
    if ts_val is None or ts_val == 0:
        return "N/A"
    try:
        if isinstance(ts_val, (int, float)):
            return datetime.fromtimestamp(
                ts_val / 1000 if ts_val > 1e12 else ts_val, tz=timezone.utc
            ).strftime("%H:%M:%S")
        return str(ts_val)
    except Exception:
        return str(ts_val)


def _build_decision_checklist(analysis: Dict, params: Dict) -> list:
    """Build structured checklist for Obs.decision_report()."""
    score = analysis.get("total_score", 0)
    quality = analysis.get("quality_data", {}).get("total", 0)
    confidence = analysis.get("confidence", 0)
    probability = analysis.get("probability", 0)
    rr = params.get("rr", 0)
    risk_pct = params.get("risk_pct", 0)
    htf_aligned = analysis.get("htf_data", {}).get("aligned", False)
    smc_ok = analysis.get("smc_data", {}).get("institutional_grade", False)
    regime = analysis.get("regime_data", {}).get("state", "Unknown")
    rejection = analysis.get("rejection_data", {}).get("reasons", [])
    trend = analysis.get("regime_data", {}).get("state", "Unknown")

    return [
        {"name": "Score >= 70",        "current": f"{score:.0f}",   "required": "70",     "passed": score >= 70,        "module": "strategies.py"},
        {"name": "Quality >= 60",      "current": f"{quality:.0f}", "required": "60",     "passed": quality >= 60,      "module": "strategies.py"},
        {"name": "Confidence >= 50",   "current": f"{confidence:.0f}", "required": "50",  "passed": confidence >= 50,   "module": "strategies.py"},
        {"name": "Probability >= 50",  "current": f"{probability:.0f}", "required": "50", "passed": probability >= 50,  "module": "strategies.py"},
        {"name": "Risk <= 2%",         "current": f"{risk_pct:.2f}%", "required": "≤2%",  "passed": risk_pct <= 2,      "module": "risk_manager.py"},
        {"name": "HTF Alignment",      "current": "YES" if htf_aligned else "NO", "required": "YES", "passed": htf_aligned, "module": "strategies.py"},
        {"name": "SMC Validated",      "current": "YES" if smc_ok else "NO", "required": "YES", "passed": smc_ok, "module": "Core/utils.py"},
        {"name": "Regime Allowed",     "current": regime,           "required": "Not SKIP", "passed": regime != "SKIP",  "module": "strategies.py"},
        {"name": "Trend Direction",    "current": trend,            "required": "Bullish/Bearish", "passed": trend not in ("SKIP", "Unknown"), "module": "strategies.py"},
        {"name": "RR >= 1.5",          "current": f"{rr:.1f}",      "required": "1.5",    "passed": rr >= 1.5,          "module": "risk_manager.py"},
        {"name": "No Rejection Reas.", "current": str(len(rejection)), "required": "0",   "passed": len(rejection) == 0, "module": "strategies.py"},
    ]


def _build_smc_checks(smc_data: Dict) -> list:
    """Build SMC strategy checks for Obs.strategy_check()."""
    details = smc_data.get("details", {})
    structures = smc_data.get("detected_structures", [])
    return [
        {"name": "BOS (Break of Structure)", "current": smc_data.get("direction", "?"), "required": "Bullish/Bearish", "status": bool(smc_data.get("direction"))},
        {"name": "CHoCH (Change of Char.)",  "current": str(structures), "required": "≥1 structure", "status": bool(structures)},
        {"name": "Liquidity Sweep",          "current": "YES" if details.get("has_liq_sweep") else "NO", "required": "YES", "status": bool(details.get("has_liq_sweep"))},
        {"name": "Order Block",               "current": "YES" if smc_data.get("institutional_grade") else "NO", "required": "YES", "status": bool(smc_data.get("institutional_grade"))},
        {"name": "FVG / Retest",              "current": "YES" if details.get("has_retest") else "NO", "required": "YES", "status": bool(details.get("has_retest"))},
        {"name": "Volume Confirmation",       "current": "YES" if details.get("has_volume") else "NO", "required": "YES", "status": bool(details.get("has_volume"))},
    ]


# ══════════════════════════════════════════════════════════════════
# AIEngine
# ══════════════════════════════════════════════════════════════════

class AIEngine:
    """
    Institutional AI analysis and signal-generation engine.

    Dual mode:
      • Monitoring-only (default): public Binance endpoints, no API keys.
      • Authenticated: BINANCE_API_KEY + BINANCE_API_SECRET for higher limits.

    Every decision is fully transparent via Core.observability.Obs.
    """

    def __init__(self, bot=None):
        self.bot = bot
        self.strategies = InstitutionalStrategies()
        self._last_analysis = {}
        self._analysis_lock = asyncio.Lock()

        self._has_credentials = bool(
            BINANCE_API_KEY and BINANCE_API_KEY.strip()
            and BINANCE_API_SECRET and BINANCE_API_SECRET.strip()
        )
        Obs.event_log(
            "AIEngine", "__init__",
            f"Mode: {'Authenticated' if self._has_credentials else 'Monitoring-only'}",
            status="OK"
        )

    async def get_market_data(self, symbol: str, timeframe: str = "15m",
                              limit: int = 500) -> pd.DataFrame:
        import ccxt.async_support as ccxt

        t0 = time.time()
        exchange_kwargs: dict = {"enableRateLimit": True}
        if self._has_credentials:
            exchange_kwargs["apiKey"] = BINANCE_API_KEY
            exchange_kwargs["secret"] = BINANCE_API_SECRET

        exchange = ccxt.binance(exchange_kwargs)
        try:
            ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
            elapsed = time.time() - t0
            Obs.api_rest_call(f"fetch_ohlcv/{symbol}/{timeframe}", elapsed_ms=elapsed * 1000)
            return df
        except Exception as e:
            Obs.error_full("AIEngine", "get_market_data", type(e).__name__,
                           str(e), input_data={"symbol": symbol, "tf": timeframe},
                           cause="Binance REST API unreachable or rate limited",
                           fix="Check network, retry after cooldown")
            return pd.DataFrame()
        finally:
            await exchange.close()

    async def analyze_and_trade(self, symbol: str):
        """Main analysis pipeline — fully observable."""
        async with self._analysis_lock:
            async with AsyncSessionLocal() as session:
                t_cycle = time.time()
                perf = {}  # per-phase timings
                diag_logger = DiagnosticLogger(symbol)

                # ── Phase 1: Data Acquisition ──
                t1 = time.time()
                df = await self.get_market_data(symbol, timeframe="15m", limit=300)
                df_htf = await self.get_market_data(symbol, timeframe="4h", limit=100)
                perf["Data Fetch"] = time.time() - t1

                if df.empty:
                    Obs.event_log("AIEngine", "analyze_and_trade",
                                  f"{symbol}: empty DataFrame", status="FAIL")
                    return
                Obs.market_data_loaded(symbol, df, df_htf, perf["Data Fetch"])

                # ── Phase 2: Core Analysis ──
                t2 = time.time()
                try:
                    analysis = self.strategies.analyze(df, df_htf=df_htf, symbol=symbol)
                except Exception as e:
                    Obs.error_full("AIEngine", "strategies.analyze",
                                   type(e).__name__, str(e),
                                   input_data={"symbol": symbol},
                                   cause="Strategy engine crashed",
                                   fix="Check strategies.py logic and input data shape")
                    return
                perf["Strategy Analysis"] = time.time() - t2

                # ── Strategy Transparency (DEBUG) ──
                if is_level(Level.DEBUG):
                    # SMC strategy check
                    smc = analysis.get("smc_data", {})
                    smc_checks = _build_smc_checks(smc)
                    smc_score = smc.get("confidence", 0) if smc_checks else 0
                    smc_passed = smc.get("institutional_grade", False)
                    Obs.strategy_check(
                        "Smart Money Concept (SMC)",
                        smc_checks, smc_score, smc_passed,
                        reason="SMC validated" if smc_passed else "Missing SMC confirmation"
                    )

                    # Regime strategy
                    reg = analysis.get("regime_data", {})
                    reg_checks = [
                        {"name": "Trend Detected", "current": reg.get("state", "?"),
                         "required": "Not SKIP", "status": reg.get("state", "SKIP") != "SKIP"},
                        {"name": "Trend Strength", "current": f"{reg.get('trend_strength', 0):.0f}%",
                         "required": "≥30%", "status": reg.get("trend_strength", 0) >= 30},
                    ]
                    Obs.strategy_check(
                        "Market Regime",
                        reg_checks, reg.get("confidence", 0),
                        reg.get("state", "SKIP") != "SKIP",
                        reason=f"Regime: {reg.get('state', 'Unknown')}"
                    )

                # ── Phase 3: Decision Engine ──
                t3 = time.time()
                try:
                    params = self.strategies.get_trade_params(df, side=analysis["verdict"])
                except Exception as e:
                    Obs.error_full("AIEngine", "get_trade_params",
                                   type(e).__name__, str(e),
                                   input_data={"symbol": symbol, "verdict": analysis.get("verdict")},
                                   cause="Risk manager failed to compute trade params",
                                   fix="Check RiskManager.calculate_sl_tp and entry price")
                    return

                # ── Build reasons ──
                reasons_list = analysis.get("reasons", [])
                formatted_reasons = []
                for r in reasons_list:
                    if isinstance(r, dict):
                        name = r.get("name", "Unknown")
                        curr = r.get("current_value", "?")
                        req = r.get("required_value", "?")
                        formatted_reasons.append(f"{name}({curr}/{req})")
                    else:
                        formatted_reasons.append(str(r))
                reason_text = " | ".join(formatted_reasons) if formatted_reasons else "No specific reasons"

                # ── Save shadow trade ──
                from Core.utils import make_json_safe
                new_shadow = ShadowTrade(
                    symbol=symbol,
                    indicators_snapshot=make_json_safe(analysis),
                    market_state=analysis.get("regime_data", {}).get("state", "Unknown"),
                    score=analysis.get("total_score", 0),
                )
                session.add(new_shadow)
                await session.commit()
                Obs.db_query("INSERT", "shadow_trades_v4", elapsed_ms=(time.time()-t3)*1000)

                # ── PERFORMANCE SUMMARY (DEBUG) ──
                total_cycle = time.time() - t_cycle
                perf["Decision + DB"] = time.time() - t3
                perf["TOTAL CYCLE"] = total_cycle
                Obs.perf_summary(perf)

                # ── DECISION REPORT (ALWAYS — full box) ──
                checklist = _build_decision_checklist(analysis, params)
                verdict = analysis.get("verdict", "SKIP")
                Obs.decision_report(
                    symbol=symbol,
                    verdict=verdict,
                    confidence=analysis.get("confidence", 0),
                    probability=analysis.get("probability", 0),
                    quality=analysis.get("quality_data", {}).get("total", 0),
                    risk_pct=params.get("risk_pct", 0),
                    rr=params.get("rr", 0),
                    conditions=checklist,
                    reasons=reason_text,
                )

                # ── Final decision box ──
                decision_data = {
                    "verdict": verdict,
                    "confidence": analysis["confidence"],
                    "probability": analysis["probability"],
                    "risk_pct": params["risk_pct"],
                    "rr": params["rr"],
                    "reason": reason_text,
                }

                if verdict == "SKIP":
                    return

                # ── Trade validation ──
                if params.get("rr", 0) < 1.5:
                    Obs.event_log("AIEngine", "validation",
                                  f"{symbol}: RR {params['rr']:.1f} < 1.5 — rejected",
                                  status="FAIL")
                    return

                # ── Telegram Alert ──
                if self.bot:
                    await self.send_signal_alert(symbol, analysis, params)

    async def send_signal_alert(self, symbol: str, analysis: Dict, params: Dict):
        emoji = "🚀" if analysis["verdict"] == "BUY" else "🔻"
        msg = (
            f"{emoji} **تنبيه مؤسسي جديد: {symbol}**\n\n"
            f"🎯 **القرار:** {analysis['verdict']}\n"
            f"📊 **الثقة:** {analysis['confidence']}%\n"
            f"📈 **الاحتمالية:** {analysis['probability']}%\n"
            f"⚖️ **العائد للمخاطرة:** 1:{params['rr']}\n\n"
            f"📍 **نقطة الدخول:** `{params['entry']:.8f}`\n"
            f"🛑 **وقف الخسارة:** `{params['stop']:.8f}`\n"
            f"🏁 **الهدف:** `{params['target']:.8f}`\n\n"
            f"📝 **الأسباب:** {analysis.get('reason', 'تحليل SMC متكامل')}"
        )
        try:
            await self.bot.send_message(chat_id=ADMIN_ID, text=msg, parse_mode="Markdown")
            Obs.event_log("AIEngine", "send_signal_alert",
                          f"{symbol}: {analysis['verdict']} signal sent to Telegram")
        except Exception as e:
            Obs.error_full("AIEngine", "send_signal_alert",
                           type(e).__name__, str(e),
                           input_data={"symbol": symbol},
                           cause="Telegram send failed",
                           fix="Check bot permissions and ADMIN_ID")
