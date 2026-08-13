# جرد ما قبل التنظيف — 2026-08-13

## المستودع

المستودع `mkkh01/CT` كان على الفرع الرئيسي في commit `891ef4d` بعنوان `Remove repository contents`، لذلك استُعيدت آخر نسخة غير فارغة من commit `34f9352` على فرع عمل محلي اسمه `ifvg-system` دون تعديل الفرع الرئيسي. النسخة السابقة كانت نظام توصيات Binance Spot ومتابعة افتراضية فقط؛ لا تحتوي على تنفيذ أوامر حقيقية ولا على مفاتيح Binance.

المكونات السابقة تشمل WebSocket وREST لبيانات Binance العامة، استراتيجية EMA/ADX/ATR للاختراق، محرك مراكز افتراضية، Supabase REST، Redis، Telegram، Flask dashboard، واختبارات متعددة. ملف README السابق ينص صراحةً على أن التنفيذ الحقيقي معطل وأن المراكز افتراضية.

## مشروع Supabase

المشروع المطابق للرابط هو:

- project_id/ref: `licqbfixgyzrahuscwnh`
- name: `Trading_bot`
- region: `eu-west-1`
- status: `ACTIVE_HEALTHY`
- database engine: PostgreSQL 17.6.1.121

الجداول الحالية في `public` هي: `bot_settings` (صف واحد)، `signals` (0)، `virtual_positions` (0)، `trade_events` (0)، `system_events` (888)، و`runtime_state` (صف واحد). جميعها RLS-enabled بحسب فحص MCP.

لا توجد Edge Functions حاليًا. توجد migrations تاريخية مرتبطة بنظام CT السابق، منها reset_public_schema_for_ct_spot_system_v2 وcreate_runtime_state وlive_data_source. الامتدادات المثبتة الفعلية الظاهرة هي pgcrypto وuuid-ossp وpg_stat_statements وsupabase_vault وبعض امتدادات Supabase النظامية؛ لا توجد حاجة لإزالة الامتدادات في عملية تنظيف public.

## قرار نطاق التنظيف

سيتم تنظيف بيانات ومخطط `public` الخاص بالمشروع السابق بعد إنشاء نسخة احتياطية محلية قابلة للاسترجاع، مع إبقاء مخططات Supabase النظامية مثل `auth`, `storage`, `extensions`, و`vault` خارج الحذف ما لم يطلب المستخدم صراحةً حذفها. هذا يحافظ على حسابات Supabase وملفات التخزين وإعدادات المنصة، ويزيل فقط أثر التطبيق السابق من مساحة العمل العامة.

## فجوة مهمة للتداول الحي

المستودع السابق لا يحتوي على `BINANCE_API_KEY` أو `BINANCE_API_SECRET`، والطلب الحالي قدّم مفاتيح Supabase/Redis/Telegram فقط. لذلك يمكن بناء محرك IFVG وبيانات Binance العامة والمحاكاة/forward testing، لكن لا يمكن تفعيل تنفيذ أوامر حقيقية على Binance دون مفاتيح تنفيذ منفصلة وصلاحيات محدودة، وسيبقى execution gate مغلقًا افتراضيًا.

## نتيجة النسخ الاحتياطي والتنظيف

أُنشئت نسخة احتياطية محلية في `backups/supabase_20260813.tar.gz`، وتتضمن نتائج قراءة جميع الجداول الحالية، المخطط السابق، والجرد. SHA-256 للنسخة: `0d88a5fa422cc9f31ca102056ad354bd9ed358510022fca4308a7c19ac950a11`.

طُبقت migration باسم `reset_public_schema_for_ifvg_trading_system` وأسقطت `public` وأعادته فارغًا مع امتيازات Supabase الأساسية. لم تُلمس مخططات `auth` أو `storage` أو `vault`، ولم توجد Edge Functions. تحقق `list_tables` بعد العملية من أن `public` لا يحتوي أي جدول.
