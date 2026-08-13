# مواصفة نظام IFVG للعملات الرقمية

## الهدف

تحويل تعريف IFVG إلى محرك حتمي قابل للاختبار يعمل على شموع Binance Spot المغلقة، مع سياق أعلى زمنيًا، وإدارة مخاطرة، وسجل دائم، ومراحل paper وtestnet وlive منفصلة. لا يجوز أن يرسل النظام أمرًا حقيقيًا في الإعداد الافتراضي.

## الإعداد الافتراضي

| المجال | الافتراضي |
|---|---|
| exchange | Binance Spot |
| data source | Binance public REST + WebSocket |
| execution mode | paper |
| live trading | disabled |
| entry timeframe | 15m |
| higher timeframe | 4h |
| trigger | close-through + retest على شموع مغلقة |
| FVG geometry | wick-based three-candle |
| inversion | close body beyond opposite edge |
| max risk/trade | 0.5% من رأس المال الورقي/المحدد |
| daily loss lock | 2% افتراضيًا وقابل للتعديل |
| max open positions | 3 |
| duplicate signal | idempotency key تمنع التكرار |

هذه الإعدادات ليست ادعاءً بأنها الأفضل؛ هي مواصفة أولية قابلة للمقارنة والاختبار، ويجب عدم تغييرها بعد رؤية النتائج إلا بإصدار نسخة استراتيجية جديدة.

## مراحل التنفيذ

1. **Paper:** بيانات حقيقية، لا أوامر؛ المراكز افتراضية مع رسوم وانزلاق افتراضيين.
2. **Testnet:** أوامر إلى Binance Spot Testnet بعد توفير مفاتيح منفصلة للتجربة فقط؛ لا تستخدم مفاتيح الحساب الحقيقي.
3. **Live:** لا يفتح إلا إذا كانت مفاتيح التداول موجودة، و`LIVE_TRADING_ENABLED=true`، و`LIVE_TRADING_CONFIRMATION` يطابق قيمة تأكيد يحددها المستخدم، وتم اجتياز reconciliation وhealth checks. هذه الطبقة ستبقى مغلقة في التسليم الحالي دون مفاتيح Binance.

## محرك IFVG

يستقبل آخر الشموع المغلقة فقط. يكتشف Bullish FVG إذا `high(c1) < low(c3)`، وBearish FVG إذا `low(c1) > high(c3)`. يحفظ المنطقة وحدودها والشموع المنشئة. عند إغلاق جسم شمعة خلف الطرف المقابل، يقلب المنطقة إلى IFVG. لا يعتبر الظل وحده انقلابًا في النسخة المحافظة. بعد الانقلاب ينتظر retest، ثم يمكنه إصدار Signal إذا اجتاز السياق الأعلى والفلتر السعري.

كل قرار يحفظ في diagnostics: تعريف المنطقة، حدودها، وقت تكوّنها، وقت الانقلاب، نوع retest، اتجاه السوق الأعلى، السيولة/البنية، أسباب الرفض، وأسعار الدخول والوقف والهدف. لا توجد إشارات مبهمة من نوع `NO_SIGNAL` دون سبب قابل للمراجعة.

## طبقة السياق والمرشحات

السياق الأعلى يحدد الاتجاه أو الحالة العرضية، والـdraw on liquidity، وموقع premium/discount من نطاق مُعرّف. يمكن تفعيل liquidity sweep وmarket structure shift وSMT كمرشحات منفصلة. كل مرشح feature مستقل في `signal_features` حتى يمكن قياس أثره بدل نسب النجاح إلى IFVG ككتلة واحدة.

## طبقة المخاطرة

قبل إنشاء order intent تتحقق من: صحة السعر والكمية وفق `exchangeInfo`، الحد الأقصى للمراكز، عدم وجود مركز على الرمز نفسه، حد الخسارة اليومية، حد التعرض الكلي، عمر البيانات، الاتصال، عدم وجود خبر/حالة توقف يدوية، وسلامة وقف الخسارة والهدف. حجم المركز يحسب من `risk_amount / stop_distance` ثم يقيد بحد رأس المال والكمية الدنيا ودقة lot/price filters.

قاطع الحماية يوقف فتح مراكز جديدة عند stale data، انقطاع User Data Stream، فشل reconciliation، تكرر أخطاء API، اختلاف الرصيد، تجاوز الخسارة اليومية، أو وجود أمر بحالة UNKNOWN. لا يعيد المحاولة بلا حدود، ولا يكرر POST order بعد 5xx قبل الاستعلام عن حالة order باستخدام clientOrderId.

## طبقة التنفيذ

تحتوي على واجهة موحدة `ExecutionAdapter`: `get_account_state`, `place_entry`, `place_protective_exit`, `cancel_order`, `get_order`, `reconcile`. يكون PaperAdapter افتراضيًا، TestnetAdapter وBinanceLiveAdapter منفصلين. live adapter يستخدم توقيع Binance الرسمي ويحترم filters وrate limits وrecvWindow وUser Data Stream، ويعالج 5xx على أنه execution status unknown لا فشلًا مؤكدًا.

للمركز الحي، يجب حفظ order intent قبل الإرسال، ثم response وexchange order id، ثم event من User Data Stream، ثم reconciliation. لا يكتفي النظام برد REST الأول لتحديد أن المركز فُتح أو أُغلق.

## طبقة التخزين

الجداول الجديدة: `bot_settings`, `market_candles`, `fvg_zones`, `ifvg_zones`, `signal_features`, `signals`, `orders`, `positions`, `risk_events`, `system_events`, و`runtime_state`. جميعها RLS-enabled، ولا توجد سياسات عامة، ويستخدم الخادم service-role key فقط. Redis cache وتسلسل locks ليسا مصدر الحقيقة؛ Supabase هو المصدر الدائم.

## المراقبة

Health endpoint يفرق بين process alive وmarket data fresh وstrategy ready وexecution reconciled. Telegram يستقبل الإشارات والحالات والأخطاء الحرجة، لكنه لا يستطيع تفعيل live من خلال رسالة عادية؛ تفعيل live يتطلب متغير تشغيل/تأكيد خارج قناة الإشعارات. Dashboard يعرض mode وlive gate وحالة البيانات وآخر شمعة وآخر reconciliation والمراكز والأوامر وrisk locks.

## معايير القبول

لا يعتبر النظام جاهزًا للتجربة إلا إذا نجح في: اختبارات وحدة هندسية لـFVG/IFVG، replay تاريخي بلا look-ahead، اختبار idempotency، إعادة تشغيل مع مركز مفتوح، انقطاع WebSocket، 429/418 backoff، 5xx unknown order، اختلاف الرصيد، rounding filters، حدود الخسارة، وpaper run مستمر. ولا يعتبر جاهزًا للتداول الحي إلا بعد اختبار Spot Testnet منفصل ومراجعة المستخدم للمخاطر والمفاتيح.

## متطلبات Binance الرسمية التي يجب احترامها

توضح وثائق Binance الرسمية أن بيانات السوق العامة يمكن أن تستخدم endpoint `https://data-api.binance.vision`، بينما تتطلب نقاط التداول الخاصة API key وتوقيعًا، وتُصنّف الصلاحيات إلى `TRADE` و`USER_DATA` و`USER_STREAM`.[1] كما تحذر الوثائق من أن استجابات 5xx لا تعني فشل التنفيذ بالضرورة؛ قد تكون حالة الأمر غير معروفة، ويجب الاستعلام عن حالة الأمر بدل إعادة إرسال POST مباشرة. وتفرض Binance حدودًا للطلبات، وتطلب التراجع عند 429 وتجنب التكرار الذي قد يؤدي إلى 418 وحظر IP.[1]

تذكر وثائق WebSocket أن اتصال WebSocket API صالح 24 ساعة تقريبًا، وأن الخادم يرسل ping كل 20 ثانية ويجب الرد بـpong، وأن Testnet له endpoint منفصل.[2] لذلك يجب أن تحتوي طبقة الاتصال على إعادة اتصال دورية، heartbeat، backoff، واستعادة حالة User Data Stream، لا الاعتماد على اتصال واحد دائم.

تؤكد مستودعات Binance الرسمية أن Spot Testnet متاح للتدرب عبر API، وأن مفاتيح Testnet منفصلة عن مفاتيح الحساب الحقيقي.[3] لا يحتوي طلب المستخدم الحالي على مفاتيح Binance، لذلك سيبقى التنفيذ الحي غير مفعّل.

[1]: https://developers.binance.com/en/docs/products/spot/rest-api
[2]: https://developers.binance.com/en/docs/products/spot/web-socket-api
[3]: https://github.com/binance/binance-spot-api-docs
