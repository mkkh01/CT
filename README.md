# Smart Trading Indicator

هذا المستودع يقدّم تطبيق ويب لتحليل سوق العملات الرقمية بصورة حتمية وقابلة للتفسير. يقرأ النظام بيانات OHLCV العامة من Binance، ويبني سياقاً متعدد الأطر الزمنية، ويحلل الاتجاه وبنية السوق والسيولة وFVG/IFVG وOrder Blocks والحجم والزخم والتذبذب، ثم يعرض `BUY` أو `SELL` أو `NO TRADE` مع خطة `Entry / Stop Loss / TP1 1:1 / TP2 1:2`.

الإصدار الحالي **مؤشر تحليلي بوضع paper فقط**. لا توجد مفاتيح تداول Binance ولا تنفيذ أوامر حقيقية. الدرجة ليست ضماناً للربح ولا احتمالاً إحصائياً معايراً.

## المكوّنات

| المكوّن | الدور |
|---|---|
| `app/market.py` | تحميل التاريخ من Binance، بث الشموع عبر WebSocket، التطبيع، إزالة التكرار، وإعادة الاتصال |
| `app/indicators.py` | ATR وEMA وRSI والتأرجحات والحجم النسبي |
| `app/analysis.py` | الاتجاه والبنية وBOS/CHOCH والسيولة وFVG/IFVG وOrder Blocks والتسجيل والمخاطر |
| `app/storage.py` | Supabase REST للحفظ الدائم وRedis للحالة السريعة والكاش |
| `app/service.py` | ربط البيانات بالتحليل ودورة حياة الإشارة والتخزين |
| `app/main.py` | FastAPI وREST وWebSocket وفحوص الصحة |
| `static/index.html` | لوحة الرسم والتحليل وخطة الإشارة |
| `supabase/migrations/0001_indicator_core.sql` | مخطط معزول خاص بالمؤشر داخل مشروع Trading_bot |

## التشغيل المحلي

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
set -a; source .env; set +a
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

ثم افتح `http://localhost:8000`. لتشغيل الواجهة دون اتصال خارجي استخدم `DISABLE_AUTO_START=true`، وستبقى الخدمة متاحة للاختبار دون تحميل Binance.

## الاختبارات

```bash
pytest -q
```

الاختبارات تغطي صحة الشموع، الحسابات الحتمية، هندسة الخطة، عقد API، تطبيع رسائل Binance، وتخزين الشموع مع إزالة التكرار والحد الأقصى للتاريخ.

## متغيرات البيئة

يستخدم الخادم المتغيرات التالية:

```env
SUPABASE_URL=
SUPABASE_KEY=
REDIS_URL=
SELECTED_SYMBOLS=BTCUSDT,ETHUSDT,...
ENTRY_TIMEFRAME=15m
STRUCTURE_TIMEFRAME=1h
HTF_TIMEFRAME=4h
MIN_SIGNAL_SCORE=80
MIN_DIRECTION_GAP=15
REQUIRE_CLOSED_CANDLE=true
RR_TP1=1.0
RR_TP2=2.0
```

لا تضع الأسرار في Git أو ملفات الواجهة. `SUPABASE_KEY` و`REDIS_URL` يستخدمان من الخادم فقط. إذا كان مفتاح Supabase من نوع `service_role` أو `sb_secret_` فلا يجوز إرساله إلى المتصفح مطلقاً.

## واجهات API

| المسار | الغرض |
|---|---|
| `GET /healthz` | فحص صحة الخدمة |
| `GET /api/v1/health` | حالة التطبيق والبيانات والتكاملات |
| `GET /api/v1/symbols` | العملات المتابعة، بحد أقصى 20 افتراضياً |
| `GET /api/v1/timeframes` | الأطر الزمنية وخرائط MTF |
| `GET /api/v1/candles/{symbol}/{timeframe}` | الشموع التاريخية الموجودة في الذاكرة |
| `GET /api/v1/analysis/{symbol}/{timeframe}` | آخر تحليل وقرار وأسباب |
| `GET /api/v1/signals/{symbol}/{timeframe}` | سجل الإشارات |
| `GET /api/v1/signals/active` | الإشارات الحالية |
| `GET /api/v1/trades` | سجل الصفقات مع إمكانية التصفية |
| `GET /api/v1/trades/current` | الصفقات الحالية: مؤكدة، معلقة، نشطة، أو وصلت إلى TP1 |
| `GET /api/v1/trades/completed` | الصفقات المنجزة: TP2 أو SL أو منتهية أو ملغاة |
| `GET /api/v1/settings` | الإعدادات العامة غير السرية |
| `WS /ws/market` | تحديثات حالة بيانات السوق |
| `WS /ws/analysis` | تحديثات حالة التحليل |
| `WS /ws/signals` | تحديثات حالة الإشارات |

## Supabase وRedis

أُضيفت جداول منفصلة حتى لا تغيّر المواصفة الجديدة الجداول القديمة في مشروع `Trading_bot`: `indicator_symbols` و`indicator_candles` و`indicator_analysis_snapshots` و`indicator_signals` و`indicator_trades` و`indicator_runtime_state` و`indicator_settings`. جميعها مفعّل عليها RLS، ويُمنح الوصول للخادم عبر دور الخدمة فقط. تعرض الواجهة الآن الصفقات الحالية والمنجزة في جدولين منفصلين.

Redis ليس مصدراً للتاريخ الدائم. يستخدمه النظام للحالة الحية والكاش ومفاتيح التحليل والإشارة. بعد إعادة التشغيل يجب أن يستطيع النظام إعادة بناء الحالة من الشموع التاريخية وقاعدة Supabase.

## Render

ملف `render.yaml` يعرّف خدمة Python واحدة على الخطة المجانية بوضع paper، وتقرأ أسرار Supabase وRedis من Render Environment Variables. الخدمة المجانية مناسبة للتجربة وMVP؛ أما تشغيل إنتاجي مستمر فيحتاج مراقبة وترقية عند تجاوز حدود CPU/RAM أو السكون أو عدد الاتصالات.

## قواعد الأمان

لا يطلب هذا الإصدار مفاتيح Binance ولا ينفذ أوامر. لا تغيّر `REQUIRE_CLOSED_CANDLE` أو حدود التسجيل دون زيادة `CONFIG_VERSION` وتشغيل الاختبارات. لا تعتبر `status=ok` وحدها دليلاً على وجود بيانات سوق حديثة؛ يجب أيضاً مراجعة `market.connected` و`last_message_at` و`data_health`.
