import os
import sys
import asyncio
import logging
import traceback
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import pandas as pd
import numpy as np

from database import AsyncSessionLocal, ShadowTrade, UserConfig
from config import (
    BINANCE_API_KEY, BINANCE_API_SECRET,
    REDIS_HOST, REDIS_PORT, REDIS_PASSWORD,
    DECISION_CONFIG,
    ADMIN_ID,
)
from Core.redis_client import redis_client
from strategies import InstitutionalStrategies
from Core.utils import safe_create_task, DiagnosticLogger

logger = logging.getLogger("CT_System")

class AIEngine:
    """
    Institutional AI analysis and signal-generation engine.

    يعمل بوضعين:
    • وضع المراقبة (افتراضي): بيانات السوق من Binance العامة بدون API keys.
    • وضع المصادقة: مع BINANCE_API_KEY + BINANCE_API_SECRET للحصول على
      معدل طلبات أعلى ووصول للنقاط الخاصة.

    في كلا الوضعين، الأخطاء تُسجّل ويعاد DataFrame فارغ
    بدلاً من انهيار event loop.
    """

    def __init__(self, bot=None):
        self.bot = bot
        self.strategies = InstitutionalStrategies()
        self._last_analysis = {}
        self._analysis_lock = asyncio.Lock()

        # Track whether live Binance credentials are available.
        self._has_credentials = bool(BINANCE_API_KEY and BINANCE_API_KEY.strip()
                                     and BINANCE_API_SECRET and BINANCE_API_SECRET.strip())
        if not self._has_credentials:
            logger.info(
                "ℹ️  [AI ENGINE] Running in monitoring-only mode — "
                "public Binance endpoints will be used for market data."
            )
        else:
            logger.info("🔐 [AI ENGINE] Authenticated Binance session enabled.")

    async def get_market_data(self, symbol: str, timeframe: str = "15m", limit: int = 500) -> pd.DataFrame:
        """جلب بيانات OHLCV من Binance عبر ccxt.

        يدعم وضعين:
        - وضع المراقبة (بدون API keys): يستخدم النقاط العامة فقط.
        - وضع المصادقة (مع API keys): يستخدم جلسة مصادقة بمعدل طلبات أعلى.

        في كلا الوضعين، الأخطاء تُسجّل ويعاد DataFrame فارغ بدلاً من رمي استثناء.
        """
        import ccxt.async_support as ccxt

        exchange_kwargs: dict = {'enableRateLimit': True}
        if self._has_credentials:
            exchange_kwargs['apiKey'] = BINANCE_API_KEY
            exchange_kwargs['secret'] = BINANCE_API_SECRET

        exchange = ccxt.binance(exchange_kwargs)
        try:
            ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            return df
        except Exception as e:
            logger.error(f"❌ [AI ENGINE] Error fetching data for {symbol}: {e}")
            return pd.DataFrame()
        finally:
            await exchange.close()

    async def analyze_and_trade(self, symbol: str):
        """المحرك الرئيسي للتحليل واتخاذ القرار"""
        async with self._analysis_lock:
            async with AsyncSessionLocal() as session:
                diag_logger = DiagnosticLogger(symbol)
                diag_logger.info(f"إطلاق المحرك المؤسسي لـ {symbol}")

                # Phase 1: Data Acquisition
                df = await self.get_market_data(symbol, timeframe="15m", limit=300)
                df_htf = await self.get_market_data(symbol, timeframe="4h", limit=100)

                if df.empty:
                    diag_logger.error("فشل جلب البيانات", "Empty DataFrame from Binance", "Data Phase")
                    return

                # Phase 2: Core Analysis Engine
                try:
                    analysis = self.strategies.analyze(df, df_htf=df_htf, symbol=symbol)
                except Exception as e:
                    diag_logger.error("خطأ في محرك التحليل", str(e), "Analysis Phase")
                    logger.error(f"❌ [AI ENGINE] Analysis Crash for {symbol}: {e}\n{traceback.format_exc()}")
                    return

                # Execution of Logs
                diag_logger.market_regime_phase(analysis["regime_data"])
                diag_logger.htf_filter_phase(analysis["htf_data"])
                diag_logger.indicators_phase(analysis["indicators_data"])
                diag_logger.smart_money_phase(analysis["smc_data"])
                diag_logger.score_engine_phase(analysis["score_data"])
                diag_logger.rejection_reasons_phase(analysis["rejection_data"])
                diag_logger.quality_phase(analysis["quality_data"])
                if analysis.get("debug_report"):
                    diag_logger.debug_report_phase(analysis["debug_report"])

                # Phase 10: Final Decision
                params = self.strategies.get_trade_params(df, side=analysis["verdict"])
                
                # إصلاح معالجة الأسباب (Reasons) لتجنب TypeError: sequence item 0: expected str instance, dict found
                reasons_list = analysis.get("reasons", [])
                formatted_reasons = []
                for r in reasons_list:
                    if isinstance(r, dict):
                        # إذا كان قاموساً (حالة الرفض)، استخرج الاسم والقيم
                        name = r.get("name", "Unknown")
                        curr = r.get("current_value", "?")
                        req = r.get("required_value", "?")
                        formatted_reasons.append(f"{name}({curr}/{req})")
                    else:
                        # إذا كان نصاً (حالة SMC)، أضفه مباشرة
                        formatted_reasons.append(str(r))
                
                reason_text = " | ".join(formatted_reasons) if formatted_reasons else "No specific reasons"

                decision_data = {
                    "verdict": analysis["verdict"],
                    "confidence": analysis["confidence"],
                    "probability": analysis["probability"],
                    "risk_pct": params["risk_pct"],
                    "rr": params["rr"],
                    "reason": reason_text
                }
                diag_logger.final_decision_phase(decision_data)

                # Phase 3: Shadow Trade
                from Core.utils import make_json_safe
                new_shadow = ShadowTrade(
                    symbol=symbol,
                    indicators_snapshot=make_json_safe(analysis),
                    market_state=analysis["regime_data"]["state"],
                    score=analysis["total_score"]
                )
                session.add(new_shadow)
                await session.commit()

                if analysis["verdict"] == "SKIP": return

                # Final Checks before Live Execution
                if params["rr"] < 1.5:
                    diag_logger.warning("Low Risk Reward", f"RR is {params['rr']} which is below 1.5", "Execution Phase")
                    return

                # Telegram Alert
                if self.bot:
                    await self.send_signal_alert(symbol, analysis, params)

    async def send_signal_alert(self, symbol: str, analysis: Dict, params: Dict):
        """إرسال تنبيه احترافي إلى تلجرام"""
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
        except Exception as e:
            logger.error(f"❌ [AI ENGINE] Telegram Alert Failed: {e}")
