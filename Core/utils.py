import asyncio
import logging
import time
import json
import traceback
from Core.observability import Obs, _now_iso as obs_now_iso
from datetime import datetime
from decimal import Decimal
import numpy as np
import pandas as pd
from typing import Any

# إعداد الـ Logger المركزي
logger = logging.getLogger("CT_System")
logger.setLevel(logging.INFO)

class JSONEncoder(json.JSONEncoder):
    """محول JSON مخصص للتعامل مع أنواع البيانات المعقدة"""
    def default(self, obj):
        if isinstance(obj, (datetime, pd.Timestamp)):
            return obj.isoformat()
        if isinstance(obj, (np.int64, np.int32, np.int16, np.int8)):
            return int(obj)
        if isinstance(obj, (np.float64, np.float32, np.float16)):
            return float(obj)
        if isinstance(obj, (np.bool_, bool)):
            return bool(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, set):
            return list(obj)
        if isinstance(obj, (pd.DataFrame, pd.Series)):
            return obj.to_dict(orient='records')
        try:
            return super().default(obj)
        except TypeError:
            return str(obj)

def make_json_safe(data: Any) -> Any:
    """تحويل البيانات إلى صيغة آمنة للـ JSON بشكل جذري"""
    if data is None:
        return None
    try:
        json_str = json.dumps(data, cls=JSONEncoder)
        return json.loads(json_str)
    except Exception as e:
        logger.error(f"JSON Safety Conversion Error: {e}")
        if isinstance(data, dict):
            return {str(k): make_json_safe(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [make_json_safe(i) for i in data]
        return str(data)

class RateLimiter:
    def __init__(self, max_calls=1200, period=60):
        self.max_calls = max_calls
        self.period = period
        self.calls = []
        self.lock = asyncio.Lock()
        self.is_banned = False
        self.ban_until = 0

    async def wait_if_needed(self, weight=1):
        async with self.lock:
            now = time.time()
            if self.is_banned:
                remaining_ban = self.ban_until - now
                if remaining_ban > 0:
                    await asyncio.sleep(remaining_ban)
                    now = time.time()
                self.is_banned = False
                print("✨ [RATE LIMITER] انتهى الحظر. بدء فترة هدوء (5s)...")
                await asyncio.sleep(5)
                now = time.time()

            self.calls = [c for c in self.calls if now - c < self.period]

            while len(self.calls) + weight > self.max_calls:
                wait_time = self.period - (now - self.calls[0])
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                now = time.time()
                self.calls = [c for c in self.calls if now - c < self.period]

            for _ in range(weight):
                self.calls.append(now)

    def set_ban(self, duration):
        self.is_banned = True
        self.ban_until = time.time() + duration
        print(f"🛑 [RATE LIMITER] تم تفعيل الحظر لـ {duration} ثانية.")

rate_limiter = RateLimiter(max_calls=1000)

class DiagnosticLogger:
    @staticmethod
    def section(phase_num, title):
        print(f"\n{'='*10} المرحلة {phase_num} : {title} {'='*10}")

    @staticmethod
    def data_phase(data_info):
        DiagnosticLogger.section(1, "DATA")
        print(f"🔹 مصدر البيانات: {data_info.get('source', 'Unknown')}")
        print(f"🔹 عدد الشموع: {data_info.get('count', 0)}")
        print(f"🔹 آخر شمعة: {data_info.get('last_candle', 'N/A')}")
        print(f"🔹 بيانات ناقصة: {'❌' if data_info.get('missing', False) else '✅ لا يوجد'}")
        print(f"🔹 وجود NaN: {'❌ نعم' if data_info.get('has_nan', False) else '✅ لا يوجد'}")
        print(f"🔹 وجود Duplicate: {'❌ نعم' if data_info.get('has_duplicate', False) else '✅ لا يوجد'}")
        print(f"🔹 وقت تحميل البيانات: {data_info.get('load_time', 'N/A')}")
        print(f"🔹 زمن التنفيذ: {data_info.get('exec_time', 0):.3f}s")
        if data_info.get('error'):
            print(f"🛑 توقف: {data_info.get('error')}")

    @staticmethod
    def market_regime_phase(regime_data):
        DiagnosticLogger.section(2, "Market Regime")
        print(f"📈 النظام المكتشف: {regime_data.get('state', 'N/A')}")
        print(f"🎯 درجة الثقة: {regime_data.get('confidence', 0)}%")
        print(f"📊 قوة الترند: {regime_data.get('trend_strength', 0)}%")
        print(f"📊 القيم المستخدمة:")
        values = regime_data.get('values', {})
        for k, v in values.items():
            print(f"   - {k}: {v}")
        print(f"📝 سبب الاختيار: {regime_data.get('reason', 'N/A')}")

    @staticmethod
    def htf_filter_phase(htf_data):
        DiagnosticLogger.section(3, "HTF Filter")
        print(f"🏷️ الحالة: {htf_data.get('status', 'N/A')}")
        print(f"🧭 قرار الفلتر: {htf_data.get('decision_state', 'N/A')}")
        print(f"🔗 متوافق: {'✅' if htf_data.get('aligned') else '❌'}")
        print(f"🎯 Penalty Confidence: {htf_data.get('confidence_penalty', 0)}")
        print(f"📉 Penalty Probability: {htf_data.get('probability_penalty', 0)}")
        print(f"📌 الحد الأدنى للشموع: {htf_data.get('required_candles', 'N/A')}")
        print(f"📌 الشموع المتوفرة: {htf_data.get('available_candles', 'N/A')}")
        print(f"💬 السبب: {htf_data.get('reason', 'N/A')}")

    @staticmethod
    def indicators_phase(ind_data):
        DiagnosticLogger.section(4, "Indicators")
        for name, details in ind_data.items():
            status = details.get('status') or details.get('status_buy') or details.get('status_sell')
            icon = "✅" if status else "❌"
            required = details.get('required') or details.get('required_buy') or details.get('required_sell') or "None"
            print(f"{icon} {name:12} | Current: {details.get('current')} | Required: {required} | Status: {icon}")

    @staticmethod
    def smart_money_phase(smc_data):
        DiagnosticLogger.section(5, "Smart Money")
        print(f"📊 الاتجاه: {smc_data.get('direction', 'N/A')}")
        print(f"📊 القوة: {smc_data.get('strength', 0)}")
        print(f"🎯 الثقة: {smc_data.get('confidence', 0)}%")
        print(f"🏛️ Institutional Grade: {'✅' if smc_data.get('institutional_grade') else '❌'}")
        print(f"🐂 نقاط الشراء: {smc_data.get('bullish_score', 0)}")
        print(f"🐻 نقاط البيع: {smc_data.get('bearish_score', 0)}")
        print("-" * 30)
        print("💎 الهياكل المكتشفة:")
        for structure in smc_data.get('detected_structures', []):
            print(f"   - {structure}")
        details = smc_data.get('details', {})
        print("-" * 30)
        print(f"🌊 سحب سيولة: {'✅' if details.get('has_liq_sweep') else '❌'}")
        print(f"🏗️ هيكل مكتمل: {'✅' if details.get('has_structure') else '❌'}")
        print(f"🔁 إعادة اختبار: {'✅' if details.get('has_retest') else '❌'}")
        print(f"📦 حجم مؤكد: {'✅' if details.get('has_volume') else '❌'}")

    @staticmethod
    def strategy_validation_phase(validation_data):
        DiagnosticLogger.section(6, "Strategy Validation")
        conditions = validation_data.get('conditions', [])
        success_count = 0
        fail_count = 0
        if not conditions:
            print("⚪ لا توجد شروط محددة للتحقق.")
        for cond in conditions:
            status = cond.get('status', False)
            icon = "✅" if status else "❌"
            current = cond.get("current_value", "N/A")
            required = cond.get("required_value", "N/A")
            impact = cond.get("impact", 0)
            fix = cond.get("suggested_fix", "N/A")
            print(f"{icon} {cond.get('name')} | Current: {current} | Required: {required} | Impact: {impact} | Fix: {fix}")
            if status:
                success_count += 1
            else:
                fail_count += 1
        print(f"📊 النتيجة: {success_count} ناجح | {fail_count} فاشل")

    @staticmethod
    def score_engine_phase(score_data):
        DiagnosticLogger.section(7, "Score Engine")
        breakdown = score_data.get('breakdown', {})
        if not breakdown:
            print("🔹 لا يوجد تفصيل للنقاط (يتم استخدام المجموع المباشر)")
        else:
            print(f"{'Category':<15} | {'Score':<7} | {'Reason'}")
            print("-" * 50)
            for category, details in breakdown.items():
                s = details.get('score', 0)
                m = details.get('max', 0)
                r = details.get('reason', 'N/A')
                print(f"{category:<15} | {s:>2}/{m:<2} | {r}")
            print("-" * 50)
        print(f"🎯 Final Score: {score_data.get('total', 0)}/100")

    @staticmethod
    def rejection_reasons_phase(rejection_data):
        DiagnosticLogger.section(8, "أسباب الرفض")
        reasons = rejection_data.get('reasons', [])
        if not reasons:
            print("✅ لا توجد أسباب رفض (الصفقة مقبولة مبدئياً)")
        else:
            for r in reasons:
                if isinstance(r, dict):
                    print(f"❌ {r.get('name')}")
                    print(f"   - Current: {r.get('current_value')}")
                    print(f"   - Required: {r.get('required_value')}")
                    print(f"   - Impact: {r.get('impact')}")
                    print(f"   - Fix: {r.get('suggested_fix')}")
                else:
                    print(f"❌ {r}")
            print(f"📊 إجمالي أسباب الرفض: {len(reasons)}")
            print("💡 Suggested Action: Wait for institutional confirmation or volume spike.")

    @staticmethod
    def quality_phase(quality_data):
        DiagnosticLogger.section(9, "Quality")
        breakdown = quality_data.get('breakdown', {})
        if not breakdown:
            print("🔹 لا يوجد تفصيل للجودة")
        for category, score in breakdown.items():
            print(f"🔹 {category:20}: {score}")
        print(f"💯 Total Quality: {quality_data.get('total', 0)}/100")

    @staticmethod
    def final_decision_phase(decision_data):
        DiagnosticLogger.section(10, "القرار النهائي")
        verdict = decision_data.get('verdict', 'SKIP')
        icon = "🚀 TRADE" if verdict in ["BUY", "SELL"] else "🛑 SKIP"
        print(f"📢 {icon}")
        print(f"🎯 Confidence: {decision_data.get('confidence', 0)}%")
        print(f"📈 Probability: {decision_data.get('probability', 0)}%")
        print(f"🛡️ Risk: {decision_data.get('risk_pct', 0)}%")
        print(f"💰 Expected RR: {decision_data.get('rr', 0)}")
        print(f"💬 أسباب القرار: {decision_data.get('reason', 'N/A')}")

    @staticmethod
    def debug_report_phase(debug_report):
        DiagnosticLogger.section(11, "Debug Report")
        print(f"🧩 Inputs: {debug_report.get('inputs', {})}")
        print(f"🧪 Thresholds: {debug_report.get('thresholds', {})}")
        print(f"⚖️ Weights: {debug_report.get('weights', {})}")
        print(f"🧭 Decision Path: {debug_report.get('decision_path', [])}")
        print(f"⏱️ Execution Time: {debug_report.get('execution_time_seconds', 0)}s")
        intermediate = debug_report.get("intermediate", {})
        for key, value in intermediate.items():
            print(f"   - {key}: {value}")

    @staticmethod
    def warning(msg, reason, location):
        print(f"\n⚠️ WARNING")
        print(f"🔹 Message: {msg}")
        print(f"🔹 Reason: {reason}")
        print(f"🔹 Location: {location}")

    @staticmethod
    def system(msg, **kwargs):
        extra = ""
        if kwargs:
            kv_pairs = [f"{k}: {v}" for k, v in kwargs.items()]
            extra = " | " + " | ".join(kv_pairs)
        print(f"🖥️ [SYSTEM] {msg}{extra}")

diag_logger = DiagnosticLogger()

def log_api_request(symbol, timeframe, source, from_cache=False, execution_time=0, **kwargs):
    status = "CACHE HIT" if from_cache else "CACHE MISS (REST)"
    now = datetime.now().strftime("%H:%M:%S")
    print(f"📝 [{now}] {status} | {symbol} | {timeframe} | {source} | {execution_time:.3f}s")


# ══════════════════════════════════════════════════════════════════
# safe_create_task — إعادة كتابة جذرية مع دعم إعادة التشغيل
# ══════════════════════════════════════════════════════════════════

_running_tasks: dict[str, asyncio.Task] = {}
_task_restart_counts: dict[str, int] = {}
_task_creation_times: dict[str, float] = {}
_task_creators: dict[str, str] = {}

def safe_create_task(coro, name=None, restart=True, restart_delay=5, max_restarts=10, creator: str = "Unknown"):
    """
    إنشاء Task مع:
    - تسجيل كامل للأخطاء + traceback
    - إعادة تشغيل تلقائية إذا ماتت (إذا restart=True)
    - حد أقصى لعدد مرات إعادة التشغيل
    - تسجيل تفصيلي لحالة المهمة وحوادثها
    """
    task_name = name or coro.__name__ if hasattr(coro, '__name__') else str(coro)

    def _schedule():
        task = asyncio.create_task(coro, name=task_name)
        _running_tasks[task_name] = task
        _task_creation_times[task_name] = time.time()
        _task_creators[task_name] = creator

        def _on_done(t):
            _running_tasks.pop(task_name, None)
            elapsed_time = time.time() - _task_creation_times.pop(task_name, time.time())
            task_creator = _task_creators.pop(task_name, "Unknown")

            try:
                t.result()
                logger.info(f"✅ [TASK] {task_name} finished successfully in {elapsed_time:.2f}s.")
            except asyncio.CancelledError:
                logger.info(f"[TASK] {task_name} cancelled (expected shutdown).")
            except Exception as e:
                tb = traceback.format_exc()
                local_vars = t.get_coro().cr_frame.f_locals if hasattr(t.get_coro(), 'cr_frame') else {}
                logger.error(f"❌ [TASK] {task_name} crashed:\n{tb}")
                Obs.task_crash_report(
                    task_name=task_name,
                    why=str(e),
                    where=f"{t.get_coro().__qualname__} in {t.get_coro().__code__.co_filename}:{t.get_coro().__code__.co_firstlineno}",
                    traceback_str=tb,
                    local_vars=local_vars,
                    task_creator=task_creator
                )

                if restart:
                    count = _task_restart_counts.get(task_name, 0)
                    if count < max_restarts:
                        _task_restart_counts[task_name] = count + 1
                        logger.warning(
                            f"🔄 [TASK] Restarting {task_name} in {restart_delay}s "
                            f"(attempt {count + 1}/{max_restarts})..."
                        )
                        Obs.restart_event(
                            why=f"Task {task_name} crashed: {e}",
                            who="safe_create_task",
                            task_state=get_task_status(task_name),
                            old_task_id=str(id(t)),
                            new_task_id="N/A", # Will be filled after restart
                            duration=elapsed_time,
                            result="RESTARTING"
                        )
                        asyncio.get_event_loop().call_later(
                            restart_delay, 
                            lambda: safe_create_task(coro, name=task_name, restart=True, restart_delay=restart_delay, max_restarts=max_restarts, creator=task_creator)
                        )
                    else:
                        logger.critical(
                            f"💀 [TASK] {task_name} exceeded max restarts ({max_restarts}). Manual intervention required."
                        )
                        Obs.restart_event(
                            why=f"Task {task_name} exceeded max restarts",
                            who="safe_create_task",
                            task_state=get_task_status(task_name),
                            old_task_id=str(id(t)),
                            new_task_id="N/A",
                            duration=elapsed_time,
                            result="FAILED_MAX_RESTARTS"
                        )

        task.add_done_callback(_on_done)
        logger.info(f"🚀 [TASK] {task_name} started (restart={restart}).")
        Obs.task_status_report(
            task_name=task_name,
            status={
                "Task ID": str(id(task)),
                "Creation Time": obs_now_iso(),
                "Current State": "Running",
                "Alive": True,
                "Cancelled": False,
                "Finished": False,
                "Exception": "N/A",
                "Restart Count": _task_restart_counts.get(task_name, 0),
                "Runtime": 0, # Will be updated dynamically or on completion
                "CPU Time": "N/A", # Requires more advanced profiling
                "Memory": "N/A", # Requires more advanced profiling
                "Stack Trace": "N/A", # Only available on crash
                "Creator": creator
            }
        )
        return task

    return _schedule()

def get_task_status(task_name: str) -> dict:
    """الحصول على حالة مهمة حية"""
    task = _running_tasks.get(task_name)
    if task:
        current_state = "Running"
        if task.done():
            if task.cancelled():
                current_state = "Cancelled"
            elif task.exception():
                current_state = "Failed"
            else:
                current_state = "Finished"

        runtime = time.time() - _task_creation_times.get(task_name, time.time())

        return {
            "running": task is not None and not task.done(),
            "done": task.done() if task else None,
            "cancelled": task.cancelled() if task else None,
            "restarts": _task_restart_counts.get(task_name, 0),
            "Task ID": str(id(task)),
            "Creation Time": datetime.fromtimestamp(_task_creation_times.get(task_name, 0)).strftime("%Y-%m-%d %H:%M:%S") if _task_creation_times.get(task_name) else "N/A",
            "Current State": current_state,
            "Alive": not task.done(),
            "Cancelled": task.cancelled(),
            "Finished": task.done() and not task.cancelled() and not task.exception(),
            "Exception": str(task.exception()) if task.exception() else "N/A",
            "Restart Count": _task_restart_counts.get(task_name, 0),
            "Runtime": f"{runtime:.2f}s",
            "CPU Time": "N/A",
            "Memory": "N/A",
            "Stack Trace": "N/A",
            "Creator": _task_creators.get(task_name, "Unknown")
        }
    return {
        "running": False,
        "done": True,
        "cancelled": False,
        "restarts": _task_restart_counts.get(task_name, 0),
        "Task ID": "N/A",
        "Creation Time": "N/A",
        "Current State": "Not Running",
        "Alive": False,
        "Cancelled": False,
        "Finished": True,
        "Exception": "N/A",
        "Restart Count": _task_restart_counts.get(task_name, 0),
        "Runtime": "0.00s",
        "CPU Time": "N/A",
        "Memory": "N/A",
        "Stack Trace": "N/A",
        "Creator": _task_creators.get(task_name, "Unknown")
    }

def get_all_task_statuses() -> dict[str, dict]:
    return {name: get_task_status(name) for name in list(_running_tasks.keys())}
