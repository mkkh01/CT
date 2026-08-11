# Crypto Spot Long-Only Research Lab

مختبر بحثي قابل لإعادة التشغيل لاكتشاف ما إذا كان هناك **أثر تاريخي متين** في استراتيجيات تداول العملات المشفرة Spot Long-Only. أُعيد بناء المستودع مع أولوية لمحرك باكتيست event-driven يمنع استخدام معلومات مستقبلية، ويحتسب الرسوم والانزلاق وفارق السعر التقريبي، ويفرض تقسيمًا زمنيًا وOut-of-Sample lock.

> هذا المشروع للبحث والاختبار التاريخي وPaper Trading فقط. لا يحتوي على مفاتيح تداول ولا ينفذ أوامر حقيقية.

## التشغيل السريع

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run_research.py --config configs/config.yaml --mode full
```

للتجربة السريعة بعد تنزيل البيانات أو مع ملفات cache موجودة:

```bash
python run_research.py --config configs/config.yaml --mode smoke --no-download
```

لتنزيل البيانات والتحقق منها فقط:

```bash
python run_research.py --config configs/config.yaml --mode data
```

## ما الذي ينفذه النظام؟

يستخدم موصل Binance Spot العام لتنزيل شموع OHLCV الحقيقية ويخزنها بصيغة Parquet داخل `data/cache`. تُفحص الطوابع الزمنية، الفجوات، التكرارات، علاقات OHLC، القيم السالبة، والبيانات غير المنطقية قبل السماح باستخدامها.

يُنشئ محرك الباكتيست الإشارات عند إغلاق الشمعة، ثم ينفذ الدخول على الشمعة التالية فقط. يراقب SL وTP شمعةً بشمعة، ويستخدم سياسة محافظة عندما يلمس السعر SL وTP داخل الشمعة نفسها. كل صفقة تسجل السعر الخام، أثر الانزلاق، الرسوم، المخاطرة، الحجم، سبب الخروج، والنتيجة.

يتضمن النظام مرشحي استراتيجيات مستقلة، وتحسينًا محدودًا، وتقسيم Train/Validation/Test، وRolling Walk-Forward، وFinal OOS lock، واختبارات تكاليف وانزلاق وضوضاء، وMonte Carlo trade resampling، وتقارير CSV/JSON/Markdown.

## هيكل المشروع

| المسار | الوظيفة |
|---|---|
| `crypto_research/data` | تنزيل OHLCV والتحقق والتخزين المؤقت |
| `crypto_research/strategies` | المؤشرات ومرشحو الإشارات |
| `crypto_research/backtesting` | محرك event-driven والمقاييس والمحفظة |
| `crypto_research/validation` | التقسيم الزمني وWalk-Forward والمتانة |
| `crypto_research/reporting` | النتائج والتقارير |
| `configs/config.yaml` | إعدادات قابلة لإعادة الإنتاج |
| `run_research.py` | أمر التشغيل الواحد |
| `tests` | اختبارات وحدات تمنع الانزلاق المستقبلي والأخطاء الأساسية |

## مصادر البيانات والقيود

البيانات من واجهة Binance Spot العامة، وقد تختلف التغطية التاريخية حسب الرمز والفاصل الزمني. قائمة العملات الحالية ليست Universe تاريخيًا كاملًا، لذلك يضع التقرير تنبيهًا عن Survivorship Bias. لا تُستنتج الجاهزية للتداول الحقيقي من نتائج هذا المشروع، ولا تُعتبر النتائج نصيحة مالية.

## النتائج

تُكتب النتائج في:

- `results/experiments.csv`
- `results/trades_*.csv`
- `results/walk_forward.csv`
- `results/stress_tests.csv`
- `results/monte_carlo.json`
- `reports/final_report.md`

## مبدأ اختيار الاستراتيجية

لا يتم اختيار أعلى Win Rate منفردة. يستخدم الترتيب Expectancy موجبة خارج العينة، Profit Factor، Max Drawdown، عدد الصفقات، الثبات بين العملات والنوافذ، وحساسية التكاليف. إذا لم تُظهر النتائج ثباتًا حقيقيًا، يجب أن يقول التقرير صراحةً: `NO ROBUST EDGE FOUND`.
