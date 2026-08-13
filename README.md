# CT — نظام تداول IFVG للعملات الرقمية

هذا المستودع يحتوي على نظام تداول آلي مبني على **Inversion Fair Value Gap (IFVG)** لبيانات Binance Spot العامة، مع محرك paper قابل لإعادة التشغيل، مخطط Supabase دائم، Redis اختياري للكاش، Telegram للتنبيهات، ولوحة مراقبة Flask. تم استبدال استراتيجية EMA-breakout القديمة بمحرك IFVG مستقل قابل للاختبار.

> **تنبيه مالي:** أنا لست مستشارًا ماليًا مرخصًا؛ هذا نظام برمجي وليس ضمانًا للربح أو توصية استثمارية. التداول بالعملات الرقمية ينطوي على احتمال خسارة رأس المال، والتنفيذ الحقيقي لا يُفعّل تلقائيًا.

## الحالة الحالية

المستودع الرئيسي السابق كان فارغًا بعد commit إزالة المحتوى، لذلك استُعيدت آخر نسخة غير فارغة على فرع عمل `ifvg-system`. قاعدة Supabase المرتبطة بالمشروع `licqbfixgyzrahuscwnh` نُظفت من `public` بعد أخذ نسخة احتياطية محلية، ثم طُبق عليها مخطط IFVG الجديد. لم تُلمس مخططات `auth` أو `storage` أو `vault`.

الوضع الافتراضي هو `paper`. يستخدم هذا الوضع بيانات سوق حقيقية، لكنه لا يرسل أي أمر إلى Binance. وضع `testnet` مخصص لمفاتيح Binance Spot Testnet المنفصلة. وضع `live` محمي بثلاثة شروط: مفاتيح Binance موجودة، و`LIVE_TRADING_ENABLED=true`، وقيمة `LIVE_TRADING_CONFIRMATION` تطابق نص التأكيد المطلوب. لا توجد مفاتيح Binance في الطلب الحالي، ولذلك لا يمكن اعتماد النظام كتداول حي فعلي قبل اختبار Testnet وتزويد الأسرار المنفصلة.

## كيف يعمل IFVG

يقرأ النظام الشموع المغلقة فقط. يكتشف FVG صاعدة عندما يكون `high(candle_1) < low(candle_3)`، وFVG هابطة عندما يكون `low(candle_1) > high(candle_3)`. تتحول الفجوة إلى IFVG بعد إغلاق شمعة خلف الطرف المقابل للمنطقة، ثم ينتظر النظام إعادة اختبار مؤكدة للمنطقة. لا يعتمد الظل وحده ككسر في النسخة المحافظة. بعد ذلك يطابق اتجاه IFVG مع سياق 4h، ويحسب الدخول والوقف والهدف ونسبة R/R، ويحفظ جميع الشروط وأسباب الرفض في diagnostics.

الإشارة لا تُنشأ أثناء تكوّن الشمعة، ولا تُكرر لنفس الرمز والإطار ووقت الشمعة وإصدار الاستراتيجية. كل إشارة تحتوي على الاتجاه، حدود IFVG، سياق الإطار الأعلى، وقت الانقلاب، وقت إعادة الاختبار، وأسعار الدخول والوقف والهدف.

## بنية النظام

| المكوّن | الدور |
|---|---|
| `app/ifvg_strategy.py` | اكتشاف FVG، تحويلها إلى IFVG، retest، سياق 4h، وقرار الإشارة |
| `app/virtual_trading.py` | Paper trading مع BUY/SELL، sizing حسب المخاطرة، الرسوم، وحد الخسارة اليومية |
| `app/execution.py` | واجهة Paper/Testnet/Live وتوقيع Binance مع بوابة أمان صريحة |
| `app/binance_ws.py` | تدفق الأسعار والشموع مع bootstrap وheartbeat وreconnect وbackoff |
| `app/runtime.py` | orchestration، Telegram، التخزين، الحالة، والتنبيهات |
| `app/storage.py` | Supabase REST كمصدر حقيقة وRedis ككاش اختياري |
| `supabase/schema.sql` | المخطط الحالي لجداول candles وFVG وIFVG والإشارات والأوامر والمراكز والمخاطر |
| `render.yaml` | إعداد نشر آمن يبدأ في paper mode |
| `tests/` | اختبارات التطبيق، WebSocket، readiness، IFVG، execution gate، وTelegram |

## المتطلبات

يلزم Python 3.11 أو أحدث واتصال إنترنت. بيانات Binance العامة لا تحتاج مفاتيح. Supabase وRedis وTelegram اختيارية لتشغيل التطبيق محليًا، لكنها مطلوبة للتخزين والتنبيهات في التشغيل المنشور.

## الإعداد المحلي

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python3 -m pytest -q
DISABLE_AUTO_START=0 flask --app run:app run --host 0.0.0.0 --port 8080
```

لا تضع قيم الأسرار في GitHub أو في HTML أو JavaScript أو رسائل Telegram. استخدم مدير أسرار بيئة النشر. المتغيرات الحساسة هي `SUPABASE_KEY` و`REDIS_URL` و`TELEGRAM_BOT_TOKEN` و`TELEGRAM_CHAT_ID`، إضافة إلى مفاتيح Binance عند استخدام Testnet أو Live.

## متغيرات التشغيل الأساسية

| المتغير | القيمة/الاستخدام |
|---|---|
| `EXECUTION_MODE` | `paper` افتراضيًا، أو `testnet`، أو `live` بعد الاختبارات |
| `LIVE_TRADING_ENABLED` | `false` افتراضيًا؛ لا يُرفع إلا بقرار واعٍ |
| `LIVE_TRADING_CONFIRMATION` | يجب أن يساوي `I_UNDERSTAND_LIVE_TRADING_RISK` لتجاوز بوابة live |
| `BINANCE_API_KEY` و`BINANCE_API_SECRET` | مفاتيح منفصلة، ولا تستخدم مفاتيح Testnet في Live أو العكس |
| `BINANCE_TESTNET` | `true` افتراضيًا |
| `SUPABASE_URL` و`SUPABASE_KEY` | رابط REST ومفتاح خادمي فقط |
| `REDIS_URL` | كاش اختياري؛ لا يستخدم كمصدر حقيقة للمراكز |
| `TELEGRAM_BOT_TOKEN` و`TELEGRAM_CHAT_ID` | تنبيهات وإدارة الإعدادات |
| `EXECUTION_TIMEFRAME` | `15m` افتراضيًا |
| `HIGHER_TIMEFRAME` | `4h` افتراضيًا |
| `RISK_PER_TRADE_PCT` | `0.005` افتراضيًا |
| `DAILY_LOSS_LIMIT_PCT` | `0.02` افتراضيًا |
| `MAX_CONCURRENT_POSITIONS` | `3` افتراضيًا |

## Supabase

ملف `supabase/schema.sql` هو المخطط الحالي، وقد طُبق فعليًا على المشروع. الجداول مفعّل عليها RLS ولا توجد سياسات عامة؛ هذا مقصود لأن التطبيق خادمي ويستخدم `service_role` على الخادم فقط. لا تضع مفتاح `service_role` في الواجهة أو Telegram.

الجداول الرئيسية هي `market_candles`, `fvg_zones`, `ifvg_zones`, `signals`, `signal_features`, `orders`, `positions`, `risk_events`, `system_events`, و`runtime_state`. يحتفظ `orders` بنية الأمر وحالته و`client_order_id` لتجنب التكرار، بينما يحتفظ `positions` بالمركز وتكلفة الرسوم وسبب الإغلاق. `runtime_state` يفصل بين process health وfresh market data وreconciliation وlive gate.

## بوابة التنفيذ

طبقة التنفيذ تعالج حالتين خطرتين في واجهات التداول: استجابة 5xx لا تعني بالضرورة أن الأمر فشل، لذلك تُسجل الحالة `UNKNOWN` ويجب الاستعلام عن حالة الأمر قبل أي إعادة إرسال؛ كما يجب احترام 429 و418 و`Retry-After` وعدم تكرار الطلبات بلا backoff. لا يعتبر رد REST وحده دليلًا نهائيًا على fill؛ يجب استخدام حالة الأمر ومصدر بيانات الحساب في التشغيل الحقيقي.

قبل أي Testnet أو Live يجب إجراء تشغيل Paper طويل، ثم اختبار Testnet بمفاتيح Testnet منفصلة، ثم فحص reconciliation بعد إعادة تشغيل التطبيق، وانقطاع WebSocket، وتأخر البيانات، واختلاف الرصيد، وفشل الشبكة. لا يفعل النظام live من خلال زر Telegram عادي.

## نقاط المراقبة

تتوفر `/healthz` و`/cron/heartbeat` و`/api/status` و`/api/snapshot`، إضافة إلى `/dashboard` وواجهات dashboard التاريخية. تعرض الحالة وضع التنفيذ، سبب قفل live، اتصال WebSocket، freshness، عدد دورات الاستراتيجية، الإشارات، المراكز، وآخر الأحداث. يجب اعتبار `status=ok` دليلًا على أن عملية Flask تستجيب فقط؛ ليس دليلًا على جاهزية التداول أو صحة الاتصال بالمنصة.

## الاختبارات

```bash
python3 -m pytest -q
```

الاختبارات الحالية تغطي 36 حالة، وتشمل الاختبارات القديمة للتطبيق وWebSocket وTelegram، إضافة إلى هندسة FVG/IFVG، عدم جاهزية البيانات، ودالة رفض live دون مفاتيح أو تأكيد صريح. نتيجة آخر تشغيل ناجح: `36 passed`.

## النسخة الاحتياطية السابقة

النسخة الاحتياطية المحلية قبل تنظيف `public` موجودة خارج المستودع في `/home/ubuntu/supabase_backups/supabase_20260813.tar.gz`. قيمة SHA-256 هي `0d88a5fa422cc9f31ca102056ad354bd9ed358510022fca4308a7c19ac950a11`. تحتوي النسخة على بيانات المشروع السابق وملف المخطط؛ لا تُرفع إلى GitHub.

## مراجع التنفيذ

[1]: https://developers.binance.com/en/docs/products/spot/rest-api — Binance Spot REST API.
[2]: https://developers.binance.com/en/docs/products/spot/web-socket-api — Binance Spot WebSocket API.
[3]: https://github.com/binance/binance-spot-api-docs — مستودع وثائق Binance الرسمي وSpot Testnet.
