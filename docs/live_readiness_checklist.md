# قائمة جاهزية التداول الحي

## الحالة الحالية

الحالة الآمنة الحالية هي **Paper فقط**. محرك IFVG وPaper Engine يعملان على بيانات Binance العامة، بينما لا يفتح runtime أوامر Testnet أو Live تلقائيًا. السبب أن طلب المشروع لا يحتوي على مفاتيح Binance، ولأن التشغيل الحي يحتاج اختبارًا منفصلًا لحالات fill وreconciliation وانقطاع User Data Stream قبل تعريض أموال حقيقية.

## بوابات إلزامية قبل Testnet

| الفحص | الحالة المطلوبة |
|---|---|
| `EXECUTION_MODE` | `testnet` |
| مفاتيح Binance | مفاتيح Spot Testnet منفصلة، دون صلاحيات سحب |
| Paper run | تشغيل مستمر مع سجل نتائج وتكاليف ورسوم |
| Data readiness | الشموع المغلقة مكتملة ولا توجد بيانات stale |
| IFVG replay | لا يوجد look-ahead، والإشارة لا تُكرر |
| API handling | اختبار 429/418 و5xx وretry-after وunknown status |
| restart recovery | استعادة orders/positions من Supabase بعد إعادة التشغيل |
| manual kill switch | تعطيل فتح مراكز جديدة وإغلاق/إلغاء الأوامر المعلقة |

## بوابات إلزامية قبل Live

لا يكفي وجود مفاتيح API. يجب مراجعة حجم الحساب، حدود المخاطرة، الرموز المسموحة، precision وminNotional، الرسوم، slippage، زمن الاستجابة، وطريقة إيقاف الخدمة. يجب أن تكون مفاتيح Binance مقيدة بعنوان IP إن أمكن، دون صلاحية سحب، ومخصصة لهذا النظام وحده.

التفعيل يحتاج إلى تغيير مقصود خارج Telegram: `EXECUTION_MODE=live`، و`LIVE_TRADING_ENABLED=true`، وقيمة التأكيد الصريحة `I_UNDERSTAND_LIVE_TRADING_RISK`. ينبغي تغيير هذه القيم بعد نجاح Testnet فقط، مع حفظ سجل الموافقة والمراجعة. وجود هذه القيم لا يلغي قاطع البيانات القديمة أو قاطع reconciliation.

## ملاحظات تشغيلية

تحذّر وثائق Binance من أن استجابة 5xx قد تترك حالة التنفيذ غير معروفة، ولذلك يجب الاستعلام عن حالة الأمر قبل إعادة الإرسال.[1] كما أن 429 يتطلب التراجع، والتكرار قد يؤدي إلى 418 وحظر IP.[1] ويجب إعادة إنشاء اتصالات WebSocket الدورية والتعامل مع ping/pong وقطع الاتصال خلال دورة 24 ساعة تقريبًا.[2]

[1]: https://developers.binance.com/en/docs/products/spot/rest-api
[2]: https://developers.binance.com/en/docs/products/spot/web-socket-api
