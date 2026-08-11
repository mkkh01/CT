# تقرير دورة استهداف Win Rate المرتفعة

## الخلاصة التنفيذية

تمت إعادة فتح البحث بدل تثبيت استراتيجية واحدة، وأضيفت مرشحات Spot Long-Only انتقائية، وأهداف ربح صغيرة، ومرشح `high_confidence_reclaim`، وقاعدة Break-Even causal، وشرط صريح في بوابة الاعتماد يطلب OOS Win Rate لا يقل عن 75% بالإضافة إلى Profit Factor وExpectancy وStress وWalk-Forward.

> النتيجة الصريحة: لم تظهر في البيانات المختبرة استراتيجية تحقق Win Rate بين 75% و80% مع ربحية موجبة ومتينة بعد الرسوم والانزلاق. لذلك بقي Paper Trading وLive Trading محظورين.

## نتائج البحث الفعلية

استخدم Probe التطوير بيانات BTCUSDT وETHUSDT وBNBUSDT بفاصل 4h، ورسومًا وانزلاقًا وفارق سعر ضمن نموذج التكلفة الطبيعي. أعلى الحالات من حيث Win Rate كانت خاسرة:

| المرشح | الصفقات | Win Rate | Profit Factor | Net Profit |
|---|---:|---:|---:|---:|
| `mean_reversion_reclaim`, TP 0.25R | 140 | 80.00% | 0.6378 | -540.08 |
| `bollinger_reversion`, TP 0.25R | 196 | 78.06% | 0.5492 | -989.20 |
| `bollinger_reversion`, Threshold 55، TP 0.25R | 99 | 77.78% | 0.5311 | -549.10 |
| `mean_reversion_reclaim`, Threshold 55، TP 0.25R | 61 | 73.77% | 0.4626 | -454.49 |

هذه النتيجة تبين أن رفع Win Rate وحده يمكن تحقيقه بتصغير Take Profit، لكن الخسارة الواحدة أكبر من مجموع مكاسب كثيرة، فتظل Expectancy سالبة. هذا ليس Edge صالحًا للتداول.

اختُبرت أيضًا Stops أقرب، Thresholds أعلى، وBreak-Even بعد 0.25R و0.5R. لم ينتج أي مرشح يحقق الحد الأدنى من الصفقات مع Expectancy موجبة في Probe. أما `high_confidence_reclaim` فكان انتقائيًا إلى درجة عدم امتلاكه عينة كافية، ولذلك لم يُسمح بترقيته.

## بوابة الجاهزية

أصبح الإعداد `min_oos_win_rate: 0.75` إلزاميًا. ولا يكفي تحقيقه وحده؛ يجب أيضًا أن تكون Expectancy موجبة، وProfit Factor أعلى من الحد، والسحب ضمن الحد، وStress مربحًا، وثبات Walk-Forward مقبولًا. هذا يمنع تمرير استراتيجية ذات Win Rate مرتفعة لكنها تخسر ماليًا.

| القرار | الحالة |
|---|---|
| Spot Long-Only | نعم |
| إرسال أوامر حقيقية | غير موجود |
| Paper Trading | محظور حاليًا |
| Live Trading | محظور دائمًا في هذه النسخة |
| OOS Win Rate Target | 75% على الأقل |
| نتيجة الدورة | `FAILED_NO_ROBUST_EDGE` |

## التعديلات المرفوعة

تم رفع التعديلات إلى مستودع [mkkh01/CT](https://github.com/mkkh01/CT) في Commit `68ce462`. شملت التعديلات Strategy Factory، مرشحات الارتداد عالية الانتقائية، Break-Even causal، وبوابة Win Rate، مع بقاء اختبارات المشروع ناجحة: **5 اختبارات ناجحة**.

## لماذا لا أصف النظام بأنه جاهز حيًا؟

لأن وصفه بأنه جاهز للتداول الحي الآن سيكون مخالفًا للنتائج. مرشح حقق 80% Win Rate لكنه خسر بعد التكاليف ليس أفضل من مرشح 45% يملك Expectancy موجبة؛ كما أن تكرار التعديلات حتى الوصول إلى رقم مستهدف على نفس البيانات يرفع خطر Backtest Overfitting. توصي مراجع البحث الكمي بتسجيل عدد الاختبارات، تحديد العينة مسبقًا، عدم إعادة التعديل بعد رؤية الاختبار، واستخدام سيناريوهات Stress، لا الاكتفاء بمسار تاريخي واحد [1] [2].

## المراجع

[1]: https://portfoliooptimizationbook.com/book/8.3-dangers-backtesting.html "The Dangers of Backtesting — Portfolio Optimization"
[2]: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551 "The Deflated Sharpe Ratio"
