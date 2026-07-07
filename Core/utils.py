import asyncio
import logging
import time
import json
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
        # استخدام المحول المخصص للتحويل إلى string ثم العودة لـ dict/list
        json_str = json.dumps(data, cls=JSONEncoder)
        return json.loads(json_str)
    except Exception as e:
        logger.error(f"JSON Safety Conversion Error: {e}")
        # محاولة أخيرة للتنظيف اليدوي إذا فشل الـ JSON
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
                print(f"✨ [RATE LIMITER] انتهى الحظر. بدء فترة هدوء (5s)...")
                await asyncio.sleep(5)
                now = time.time()

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
        """المرحلة 1: DATA"""
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
        """المرحلة 2: Market Regime"""
        DiagnosticLogger.section(2, "Market Regime")
        print(f"📈 النظام المكتشف: {regime_data.get('state', 'N/A')}")
        print(f"🎯 درجة الثقة: {regime_data.get('confidence', 0)}%")
        print(f"📊 القيم المستخدمة:")
        values = regime_data.get('values', {})
        for k, v in values.items():
            print(f"   - {k}: {v}")
        print(f"📝 سبب الاختيار: {regime_data.get('reason', 'N/A')}")
        if regime_data.get('others_rejected'):
            print(f"🚫 أسباب رفض الأنظمة الأخرى: {regime_data.get('others_rejected')}")

    @staticmethod
    def htf_filter_phase(htf_data):
        """المرحلة 3: HTF Filter"""
        DiagnosticLogger.section(3, "HTF Filter")
        conditions = htf_data.get('conditions', [])
        for cond in conditions:
            icon = "✅" if cond.get('status') else "❌"
            print(f"{icon} {cond.get('name')}: {cond.get('value')}")
        
        verdict = "PASS" if htf_data.get('supported') else "REJECT"
        icon = "✅" if verdict == "PASS" else "❌"
        print(f"🏁 القرار النهائي: {icon} {verdict}")
        print(f"💬 السبب: {htf_data.get('reason', 'N/A')}")

    @staticmethod
    def indicators_phase(ind_data):
        """المرحلة 4: Indicators"""
        DiagnosticLogger.section(4, "Indicators")
        for name, details in ind_data.items():
            status = details.get('status') or details.get('status_buy') or details.get('status_sell')
            icon = "✅" if status else "❌"
            required = details.get('required') or details.get('required_buy') or details.get('required_sell') or "None"
            print(f"{icon} {name:12} | Current: {details.get('current')} | Required: {required} | Status: {icon}")

    @staticmethod
    def smart_money_phase(smc_data):
        """المرحلة 5: Smart Money"""
        DiagnosticLogger.section(5, "Smart Money")
        for item, details in smc_data.items():
            # دعم كلا التنسيقين (القديم والجديد)
            exists = details.get('exists', any(details.values()) if isinstance(details, dict) else False)
            info = details.get('info', 'Available' if exists else 'N/A')
            conf = details.get('confidence', 100 if exists else 0)
            icon = "💎" if exists else "⚪"
            print(f"{icon} {item:15} | Exist: {'✅' if exists else '❌'} | Info: {info} | Confidence: {conf}%")

    @staticmethod
    def strategy_validation_phase(validation_data):
        """المرحلة 6: Strategy Validation"""
        DiagnosticLogger.section(6, "Strategy Validation")
        conditions = validation_data.get('conditions', [])
        success_count = 0
        fail_count = 0
        if not conditions:
            print("⚪ لا توجد شروط محددة للتحقق.")
        for cond in conditions:
            status = cond.get('status', False)
            icon = "✅" if status else "❌"
            print(f"{icon} {cond.get('name')}")
            if status: success_count += 1
            else: fail_count += 1
        print(f"📊 النتيجة: {success_count} ناجح | {fail_count} فاشل")

    @staticmethod
    def score_engine_phase(score_data):
        """المرحلة 7: Score Engine"""
        DiagnosticLogger.section(7, "Score Engine")
        breakdown = score_data.get('breakdown', {})
        if not breakdown:
            print("🔹 لا يوجد تفصيل للنقاط (يتم استخدام المجموع المباشر)")
        for category, details in breakdown.items():
            s = details.get('score', 0)
            m = details.get('max', 0)
            r = details.get('reason', 'N/A')
            print(f"🔹 {category:15}: {s}/{m} | Reason: {r}")
        print(f"🎯 Final Score: {score_data.get('total', 0)}/100")

    @staticmethod
    def rejection_reasons_phase(rejection_data):
        """المرحلة 8: أسباب الرفض"""
        DiagnosticLogger.section(8, "أسباب الرفض")
        reasons = rejection_data.get('reasons', [])
        if not reasons:
            print("✅ لا توجد أسباب رفض (الصفقة مقبولة مبدئياً)")
        else:
            for r in reasons:
                print(f"❌ {r}")
            print(f"📊 إجمالي أسباب الرفض: {len(reasons)}")

    @staticmethod
    def quality_phase(quality_data):
        """المرحلة 9: Quality"""
        DiagnosticLogger.section(9, "Quality")
        breakdown = quality_data.get('breakdown', {})
        if not breakdown:
            print("🔹 لا يوجد تفصيل للجودة")
        for category, score in breakdown.items():
            print(f"🔹 {category:20}: {score}")
        print(f"💯 Total Quality: {quality_data.get('total', 0)}/100")

    @staticmethod
    def final_decision_phase(decision_data):
        """المرحلة 10: القرار النهائي"""
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
    def warning(msg, reason, location):
        print(f"\n⚠️ WARNING")
        print(f"🔹 Message: {msg}")
        print(f"🔹 Reason: {reason}")
        print(f"🔹 Location: {location}")

    @staticmethod
    def system(msg, **kwargs):
        extra = f" | {' | '.join([f'{k}: {v}' for k, v in kwargs.items()])}" if kwargs else ""
        print(f"🖥️ [SYSTEM] {msg}{extra}")

diag_logger = DiagnosticLogger()

def log_api_request(symbol, timeframe, source, from_cache=False, execution_time=0, **kwargs):
    status = "CACHE HIT" if from_cache else "CACHE MISS (REST)"
    now = datetime.now().strftime('%H:%M:%S')
    print(f"📝 [{now}] {status} | {symbol} | {timeframe} | {source} | {execution_time:.3f}s")

def safe_create_task(coro, name=None):
    """إنشاء Task مع معالجة Exceptions و Stack Trace كامل"""
    task = asyncio.create_task(coro, name=name)
    def handle_result(t):
        try:
            t.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            import traceback
            tb = traceback.format_exc()
            logger.error(f"❌ Exception in task {name or t}:\n{tb}")
    task.add_done_callback(handle_result)
    return task
