# خارطة طريق البحث الكمي: Crypto Spot Long-Only

## الهدف وقاعدة القرار

الهدف ليس تعظيم قمة الربح التاريخي، بل اكتشاف مرشح **مسطح نسبيًا، متسق، منخفض السحب، وقابل للتعميم خارج العينة**. لذلك لا يكفي أن تكون نتيجة In-Sample إيجابية؛ يجب أن تكون Expectancy خارج العينة موجبة، وأن يبقى Profit Factor مقبولًا بعد التكاليف والضوضاء، وأن تظهر الاستراتيجية ثباتًا بين العملات والنوافذ والأنظمة السوقية.

> قاعدة الرفض: إذا لم تتوافق النتائج بين النوافذ أو انهارت تحت Stress أو بقيت OOS سالبة، فالنتيجة `NO ROBUST EDGE FOUND` ولا تُنقل إلى Paper Trading أو Live Trading.

تستند هذه القاعدة إلى أن تعدد التجارب يرفع احتمال اختيار نتيجة زائفة. يقدّم Bailey وBorwein وLópez de Prado وZhu إطارًا لاحتمال Backtest Overfitting، بينما يوضح Bailey وLópez de Prado أن Deflated Sharpe Ratio يعالج تضخم الأداء الناتج عن تعدد الاختبارات وعدم طبيعية العوائد [1] [2].

## المرحلة الأولى: البيانات والـUniverse

يستخدم النظام بيانات Klines حقيقية من Binance Spot Public Market Data، ويخزنها محليًا بصيغة Parquet، ويتحقق من التكرارات والطوابع الزمنية والفجوات وعلاقات OHLC والقيم السالبة قبل السماح بالباكتيست [3] [4]. جرى تشغيل Universe فعلي من 50 زوج USDT تم اكتشافها من `exchangeInfo` وترتيبها بحسب `quoteVolume` وقت الاكتشاف.

هذه ليست قائمة تاريخية كاملة للعملات المحذوفة؛ لذلك بقي Survivorship Bias قيدًا معلنًا. كما أن الرموز الحديثة لا تملك سنوات كاملة، وهو ما يظهر في metadata. لا يجوز مقارنة رمز بدأ في 2026 برمز بدأ في 2019 وكأن لهما نفس سجل الأنظمة السوقية.

| فحص البيانات | التطبيق |
|---|---|
| التكرارات | رفض الشموع ذات timestamp مكرر |
| التسلسل الزمني | فرض UTC وترتيب تصاعدي |
| الفجوات | حساب عدد الشموع الناقصة بالنسبة للفاصل |
| علاقات OHLC | High أعلى من Open/Close/Low وLow أدنى منها |
| الشمعة المفتوحة | استبعاد آخر شمعة غير مكتملة |
| Universe | Spot فقط، USDT، حالة TRADING، مع سجل اكتشاف |
| الكاش | ملف Parquet مستقل لكل رمز وفاصل وبصمة إعدادات |

## المرحلة الثانية: Strategy Factory

بدل تعديل استراتيجية واحدة، يولّد المصنع فضاء مرشحين من Trend Pullback وTrend Breakout وMomentum Volume وLiquidity Sweep Reversal وStructure Pullback وMulti-Timeframe Trend Momentum، إضافة إلى Bollinger Reversion وEMA Cross Momentum. ويجري لكل مرشح اختبار Score Threshold وATR Stop أو Swing Stop وTake-Profit متعدد المضاعفات.

المصنع يولد مساحة أكبر من التجارب التي تُشغّل في كل دفعة. عند تقييد عدد التجارب، يستخدم النظام اختيارًا طبقيًا يضمن تمثيل كل استراتيجية بدل أن يترك Random Search استراتيجية كاملة خارج العينة بالصدفة. لا يتم اختيار أعلى Win Rate وحدها؛ بل تُستخدم Expectancy وProfit Factor وMax Drawdown وعدد الصفقات والثبات عبر العملات.

## المرحلة الثالثة: Walk-Forward وOOS Lock

يُقسّم الزمن إلى Train ثم Validation ثم Test مع Purge وEmbargo. في الدراسة الحالية جرى اختيار المعلمات على نافذة Train/Validation الأخيرة ثم تجميدها، وقياس نفس المعلمات عبر ثلاث نوافذ اختبار متتابعة. هذا يجعل النوافذ السابقة اختبارًا تاريخيًا إضافيًا للثبات، ويمنع إعادة ضبط المعلمات بعد رؤية نتيجة Test.

| الطبقة | الاستخدام |
|---|---|
| Train | توليد واختيار المرشحين أوليًا |
| Validation | ترتيب المرشحين والاختيار النهائي داخل التطوير |
| Test/OOS | اختبار مجمد لم يُستخدم لتغيير المعلمات |
| WFA | تجميع أداء نوافذ زمنية متتابعة |
| Final Gate | منع Paper/Live إذا فشلت شروط OOS أو Stress أو WFA |

## المرحلة الرابعة: Stress والأنظمة السوقية

يقسم التقرير النتائج إلى Bull وBear وSideways، مع High وLow Volatility، ويختبر الرسوم والانزلاق على مستويات Low وNormal وHigh وStress. كما يضيف ضوضاء إلى عوائد الصفقات لمحاكاة تغير نقطة التنفيذ، ويقيس Bootstrap وMonte Carlo لتوزيع النتائج واحتمال العائد الموجب.

الاستراتيجية القابلة للتعميم يجب ألا تعتمد على Bull Market فقط، ولا ينبغي أن تنهار عند زيادة بسيطة في الرسوم والانزلاق. نتيجة Normal الإيجابية التي تصبح سالبة في Stress تُصنف Fragile، حتى لو كان Net Profit التاريخي مرتفعًا.

## المرحلة الخامسة: مقاييس القرار

| المقياس | لماذا يُستخدم |
|---|---|
| OOS Expectancy | هل كل صفقة تضيف قيمة في البيانات غير المرئية؟ |
| Profit Factor | مقارنة الربح الإجمالي بالخسارة الإجمالية |
| Max Drawdown | قياس الضرر الرأسمالي في أسوأ مسار |
| Sortino | التركيز على تقلب العوائد السلبية |
| Calmar | الربح مقارنة بالسحب الأقصى |
| Trade Count | منع الثقة الزائفة من عينة صغيرة |
| Cross-Coin Stability | كشف الاعتماد على رمز واحد |
| WFA Stability | كشف اعتماد النتيجة على نافذة واحدة |
| Monte Carlo | توزيع المسارات واحتمال النتيجة الموجبة والخراب |

ينبغي أن تُستكمل لاحقًا نسخة كاملة من PBO وDeflated Sharpe Ratio على جميع التجارب المسجلة؛ لا يجوز تسمية الـrank proxy الحالي DSR كاملًا.

## المرحلة السادسة: محرك التنفيذ

في كل شمعة مغلقة، تُحسب المؤشرات من البيانات السابقة والمتاحة فقط. الإشارة تُنفذ على افتتاح الشمعة التالية، وهو نموذج محافظ لتأخير القرار. يحتسب المحرك رسوم التداول، والانزلاق، ونصف السبريد التقريبي عند الدخول والخروج. إذا لمس السعر SL وTP داخل الشمعة نفسها، تُستخدم سياسة `conservative_stop_first`. كل صفقة تسجل السعر الخام، السعر التنفيذي، الرسوم، الانزلاق، الحجم، سبب الخروج، والنتيجة.

```text
for each closed candle:
    features = causal_features(data_until_now)
    signal = strategy_factory(features)
    if signal and no_position:
        entry = next_bar_open_with_slippage_and_spread()
        position_size = risk_budget / stop_distance
        record fees, latency assumption, stop, target
    if position:
        inspect high/low in conservative order
        close on stop, target, time exit, or end of data
aggregate trades -> OOS metrics -> WFA -> stress -> Monte Carlo -> gate
```

## نتيجة دراسة الـ50 زوجًا

شُغّلت الدراسة على 50 زوج Spot حقيقي بفاصل 4h، مع بيانات تبدأ من 2019 عندما كانت متاحة، و24 تجربة ممثلة، ومعلمات مختارة مرة واحدة ثم مجمدة عبر ثلاث نوافذ OOS. أفضل مرشح كان `trend_pullback` مع Score Threshold 85 وATR Stop multiplier 2.0 وTP قدره 1.5R.

| المقياس | النتيجة |
|---|---:|
| عدد الأزواج | 50 |
| إجمالي OOS Trades | 405 |
| OOS Win Rate | 44.69% |
| OOS Profit Factor | 1.1316 |
| OOS Net Profit | 1484.05 على رأس مال ابتدائي 10000 |
| OOS Expectancy | 3.6643 |
| OOS Max Drawdown | -15.34% |
| OOS Sharpe | 1.1999 |
| Bootstrap Probability Positive | 86.45% |
| Stress Profit Factor | 0.8907 |
| WFA Windows | 3 |
| WFA Positive Windows | 1 من 3 |

رغم أن آخر نافذة OOS كانت إيجابية، فإن أول نافذتين كانتا سالبتين، وانهارت النتيجة في Stress إلى Profit Factor قدره 0.8907، ولذلك رفضت البوابة Paper Trading. هذا مثال على الفرق بين نتيجة OOS واحدة جيدة وبين Edge متين عبر الزمن.

## القرار النهائي

الاستراتيجية الحالية **غير جاهزة لـPaper Trading وغير جاهزة للتداول الحي**. القرار ليس بسبب ضعف OOS الأخير وحده، بل بسبب فشل الثبات عبر نوافذ Walk-Forward واختبار Stress. هذا هو السلوك المطلوب من النظام: يحفظ نتيجة إيجابية محتملة، لكنه يرفض تحويلها إلى قرار تشغيلي قبل إثبات الاتساق.

## المراجع

[1]: https://escholarship.org/uc/item/4w1110bb "The Probability of Backtest Overfitting"
[2]: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551 "The Deflated Sharpe Ratio"
[3]: https://developers.binance.com/en/docs/binance-spot-api-docs/rest-api/market-data-endpoints "Binance Spot Market Data Endpoints"
[4]: https://developers.binance.com/en/docs/products/spot/faqs/market_data_only "Binance Market Data Only URLs"
