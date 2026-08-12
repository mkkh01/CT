# ADX/ATR filter research

## Findings

مرجع Fidelity يوضح أن ADX يقيس قوة الاتجاه وليس اتجاهه بذاته. تشير القراءة تحت 20 عادةً إلى غياب اتجاه واضح، بينما تشير القراءة فوق 25 عادةً إلى اتجاه أقوى، ولا توجد دلالة حاسمة دائماً في المنطقة بين 20 و25. اتجاه الحركة يقرأ من مقارنة +DI و-DI، وليس من ADX وحده.

مرجع Fidelity الخاص بـ ATR، كما ظهر في نتائج البحث، يعرّف ATR بأنه متوسط True Range ويستخدم لقياس التذبذب مع احتساب الفجوات. لذلك لا ينبغي استخدام ATR وحده لمعرفة صعود أو هبوط السوق، بل كشرط صلاحية للحركة أو كقياس تطبيع للتذبذب بين العملات.

## Design decision for CT

سيستخدم الفلتر على شموع 1H التنفيذية بعدد 14 فترة:

- `ADX >= 25` كحد أدنى انتقائي لقوة الاتجاه، مع `+DI > -DI` لتأكيد أن الاتجاه صاعد لأن النظام Spot long-only.
- `ATR(14) / close >= 0.003`، أي تذبذب حقيقي لا يقل عن 0.30% من السعر، لتجنب الاختراقات داخل نطاق ضيق جداً.
- `ATR(14) / close <= 0.08` كحاجز أمان للتذبذب الشديد؛ هذه ليست إشارة بيع، لكنها تمنع الدخول عندما تكون الحركة غير مستقرة جداً.
- الرفض التفصيلي سيكون أحد القيم: `SIDEWAYS_ADX_LOW` أو `SIDEWAYS_ATR_LOW` أو `VOLATILITY_TOO_HIGH` أو `BEARISH_DIRECTIONAL_MOVEMENT`.

هذه الحدود ابتدائية قابلة للضبط من متغيرات البيئة، وليست ضماناً للربح. سيتم تطبيقها مع شروط الاستراتيجية الحالية: EMA، الاختراق، الحجم، RSI، والشمعة الصاعدة.

## Sources

- https://www.fidelity.com/viewpoints/active-investor/average-directional-index-ADX
- https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/atr

## Candle/chart classification research

مراجعة نتائج البحث ومرجع Fidelity الخاص بأنماط الشارت تؤكد أن أنماط الشموع تعتمد على جسم الشمعة وظلالها، وأن نمط engulfing يقارن جسم شمعة مع جسم الشمعة السابقة. لن يعتمد النظام على اسم نموذج وحده؛ سيحسب نسب الجسم والظلال إلى المدى الحقيقي، ثم يضع التصنيف في سياق الاتجاه.

## Planned classifications

تصنيف الشمعة الأخيرة على 1H سيكون واحداً من: `BULLISH_MARUBOZU`، `BEARISH_MARUBOZU`، `BULLISH`، `BEARISH`، `DOJI`، `HAMMER`، `SHOOTING_STAR`، أو `NEUTRAL`.

تصنيف الشارت سيكون واحداً من: `UPTREND`، `DOWNTREND`، `SIDEWAYS`، `HIGH_VOLATILITY`، أو `UNAVAILABLE`. سيجمع بين ADX و+DI/-DI وATR/price واصطفاف EMA وميل EMA؛ ADX وحده لا يحدد الاتجاه.

المراجع التي تمت مراجعتها:

- https://www.fidelity.com/viewpoints/active-investor/average-directional-index-ADX
- https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/atr
- https://www.fidelity.com/bin-public/060_www_fidelity_com/documents/learning-center/Idenitfying-Chart-Patterns.pdf
