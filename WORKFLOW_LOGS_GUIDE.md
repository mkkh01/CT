# دليل نظام سجلات سير العمل (Workflow Logs System)

## نظرة عامة

تم تطوير نظام شامل لعرض سير عمل الصفقات والتحليل والنتائج والأسباب في واجهة Render Logs. يوفر هذا النظام رؤية واضحة لكل مرحلة من مراحل معالجة الصفقة.

## المكونات الرئيسية

### 1. Workflow Logger (`monitoring/workflow_logger.py`)

وحدة متخصصة لتسجيل أحداث سير العمل بصيغة منظمة وسهلة القراءة.

**الأحداث الرئيسية:**

| نوع الحدث | الوصف |
|-----------|-------|
| `ANALYSIS_START` | بداية دورة تحليل جديدة للعملة |
| `ANALYSIS_COMPONENT` | نتائج تحليل مكون محدد (SMC, Trend, Volume) |
| `ANALYSIS_GATES` | حالة البوابات (Regime, HTF, Confidence, Risk) |
| `DECISION_APPROVED` | قرار موافقة على الصفقة مع معاملات الدخول |
| `DECISION_REJECTED` | قرار رفض الصفقة مع السبب التفصيلي |
| `TRADE_OPENED` | فتح صفقة محاكاة جديدة |
| `TRADE_CLOSED` | إغلاق صفقة مع النتيجة والسبب |
| `WORKFLOW_SUMMARY` | ملخص دوري لأداء سير العمل |

**مثال على الاستخدام:**

```python
from monitoring.workflow_logger import log_decision_approved

log_decision_approved(
    symbol="BTCUSDT",
    score=0.85,
    confidence=0.92,
    entry_price=45000.0,
    stop_loss=44500.0,
    take_profit=46000.0,
    position_size=0.5,
    execution_time_ms=125.5,
)
```

### 2. Workflow Endpoints (`app/main.py`)

ثلاث نقاط نهاية جديدة في FastAPI لاسترجاع بيانات سير العمل:

#### `GET /api/workflow/status/{symbol}`

يعيد حالة سير العمل الحالية للعملة مع أحدث القرارات والصفقات.

**مثال الاستجابة:**

```json
{
  "symbol": "BTCUSDT",
  "recent_decisions": [
    {
      "created_at": "2024-01-15T10:30:00Z",
      "final_verdict": true,
      "score": 0.85,
      "confidence": 0.92,
      "rejection_reason": null
    }
  ],
  "recent_trades": [
    {
      "opened_at": "2024-01-15T10:30:15Z",
      "status": "open",
      "direction": "long",
      "entry_price": 45000.0,
      "pnl": null,
      "close_reason": null
    }
  ]
}
```

#### `GET /api/workflow/decisions/{symbol}?hours=24`

يعيد ملخص القرارات للعملة خلال فترة زمنية محددة.

**مثال الاستجابة:**

```json
{
  "symbol": "BTCUSDT",
  "period_hours": 24,
  "total_decisions": 45,
  "approved_decisions": 12,
  "rejected_decisions": 33,
  "approval_rate": 26.67,
  "top_rejection_reasons": {
    "confidence_below_threshold: 0.70 required": 15,
    "regime_check_failed: VOLATILE regime blocks new entries": 10,
    "risk_rejected: insufficient_capital": 8
  }
}
```

#### `GET /api/workflow/trades/{symbol}?hours=24`

يعيد ملخص الصفقات للعملة خلال فترة زمنية محددة.

**مثال الاستجابة:**

```json
{
  "symbol": "BTCUSDT",
  "period_hours": 24,
  "total_trades": 12,
  "winning_trades": 8,
  "losing_trades": 4,
  "win_rate": 66.67,
  "total_pnl": 245.50
}
```

### 3. دوال استعلام Supabase (`storage/supabase.py`)

تم إضافة دالة جديدة لاسترجاع الصفقات حسب العملة:

```python
async def fetch_trades_by_symbol(
    self,
    symbol: str,
    limit: int = 100,
    status: Optional[str] = None,
) -> list[SimulatedTrade]:
    """Fetch trades for a specific symbol with optional status filter."""
```

## تدفق البيانات

```
┌─────────────────┐
│  Binance WS     │
│   (Candles)     │
└────────┬────────┘
         │
         ▼
┌─────────────────────────┐
│   Orchestrator          │
│  (Analysis & Decision)  │
└────────┬────────────────┘
         │
         ├─────────────────────────┐
         │                         │
         ▼                         ▼
    ┌─────────┐            ┌──────────────┐
    │ Approved│            │  Rejected    │
    └────┬────┘            └──────┬───────┘
         │                        │
         ▼                        ▼
    ┌──────────────┐      ┌──────────────┐
    │ Paper Trade  │      │ Logs (JSON)  │
    │  (Opened)    │      │  (Render)    │
    └────┬─────────┘      └──────────────┘
         │
         ▼
    ┌──────────────┐
    │ Supabase DB  │
    │ (Decisions & │
    │   Trades)    │
    └──────────────┘
         │
         ▼
    ┌──────────────────┐
    │ Workflow API     │
    │ Endpoints        │
    │ (Status, Summary)│
    └──────────────────┘
```

## سجلات Render

### صيغة السجلات

جميع سجلات سير العمل تتبع صيغة JSON منظمة:

```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "workflow_event": "decision_approved",
  "symbol": "BTCUSDT",
  "score": 0.85,
  "confidence": 0.92,
  "entry_price": 45000.0,
  "stop_loss": 44500.0,
  "take_profit": 46000.0,
  "position_size": 0.5,
  "risk_reward_ratio": 2.0,
  "execution_time_ms": 125.5
}
```

### مثال على تسلسل السجلات

1. **بداية التحليل:**
   ```json
   {"workflow_event": "analysis_start", "symbol": "BTCUSDT", "trigger_timeframe": "1h"}
   ```

2. **تحليل المكونات:**
   ```json
   {"workflow_event": "analysis_component", "component": "trend", "timeframe": "1h", "result": {...}}
   ```

3. **حالة البوابات:**
   ```json
   {"workflow_event": "analysis_gates", "regime": {"passed": true, "value": "TRENDING"}, ...}
   ```

4. **القرار النهائي:**
   ```json
   {"workflow_event": "decision_approved", "score": 0.85, "confidence": 0.92, ...}
   ```

5. **فتح الصفقة:**
   ```json
   {"workflow_event": "trade_opened", "trade_id": "uuid", "direction": "long", ...}
   ```

6. **إغلاق الصفقة:**
   ```json
   {"workflow_event": "trade_closed", "pnl": 245.50, "close_reason": "tp", ...}
   ```

## أسباب الرفض الشائعة

| السبب | الوصف |
|------|-------|
| `regime_check_failed` | النظام في حالة متقلبة (VOLATILE) |
| `risk_rejected` | فشل تقييم المخاطر (رأس مال غير كافي، إلخ) |
| `structure_alignment_failed` | لا توجد اتجاهات واضحة أو BOS/CHOCH |
| `confidence_below_threshold` | الثقة أقل من الحد الأدنى المطلوب |
| `htf_bias_misaligned` | إشارة الإطار الزمني الأقل تتناقض مع الإطار الأعلى |

## التكامل مع Render

### عرض السجلات في لوحة التحكم

يمكن الوصول إلى سجلات سير العمل عبر:

1. **Render Dashboard:** عرض السجلات المباشرة (JSON) في لوحة التحكم
2. **API Endpoints:** استعلام البيانات المجمعة عبر REST API
3. **Supabase Dashboard:** الوصول المباشر إلى جداول القرارات والصفقات

### مراقبة الأداء

يمكن استخدام الملخصات الدورية لمراقبة:

- معدل الموافقة على القرارات
- أسباب الرفض الأكثر شيوعاً
- معدل الفوز في الصفقات
- إجمالي الأرباح والخسائر

## التطوير المستقبلي

### التحسينات المخطط لها

1. **لوحة تحكم تفاعلية:** واجهة ويب لعرض سجلات سير العمل بشكل مرئي
2. **تنبيهات فورية:** إخطارات عند حدوث أحداث مهمة
3. **تحليل إحصائي:** رسوم بيانية وتقارير تفصيلية
4. **تصدير البيانات:** تصدير السجلات والملخصات إلى ملفات

## استكشاف الأخطاء

### المشاكل الشائعة

**المشكلة:** لا تظهر سجلات جديدة
- **الحل:** تحقق من أن المحرك قيد التشغيل (`/ready` endpoint)
- تأكد من أن البيانات تصل من Binance WS

**المشكلة:** نقاط النهاية تعيد خطأ
- **الحل:** تحقق من اتصال Supabase
- تأكد من أن جداول القرارات والصفقات موجودة

**المشكلة:** أسباب الرفض غير واضحة
- **الحل:** راجع ملف `engine/orchestrator.py` للتحقق من منطق الرفض
- تحقق من السجلات الكاملة في Render dashboard

## المراجع

- [Orchestrator Logic](./engine/orchestrator.py)
- [Paper Trade Results](./simulation/paper_trade.py)
- [Logger Configuration](./monitoring/logger.py)
- [Supabase Client](./storage/supabase.py)
