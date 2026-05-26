# --- استبدل الأجزاء المعنية في ملف bot/handlers.py بهذا الكود ---

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    if data == 'private_trades':
        # الآن عند الضغط على "الصفقات الخاصة" تظهر القائمة الفرعية (الأزرار الثلاثة)
        from bot.keyboards import get_private_trades_menu
        await query.edit_message_text(
            "🌟 *مركز التحكم بالصفقات الخاصة*\n\n"
            "هنا يمكنك تشغيل إشارات التداول المضمونة أو طلب تقرير أداء لحظي لكل ما حدث حتى الآن.",
            reply_markup=get_private_trades_menu(),
            parse_mode='Markdown'
        )

    elif data == 'elite_on' or data == 'elite_off':
        # منطق تشغيل وإيقاف "إرسال" الإشارات للمستخدم
        is_on = (data == 'elite_on')
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(UserConfig).where(UserConfig.telegram_id == ADMIN_ID))
            cfg = res.scalars().first()
            if cfg:
                cfg.elite_enabled = is_on
                await session.commit()
        
        status_text = "🟢 تم تفعيل إشارات التداول" if is_on else "🔴 تم إيقاف إشارات التداول"
        await query.edit_message_text(f"{status_text}\n\nالنظام سيستمر في العمل في الخلفية ولكن الإشعارات ستتأثر باختيارك.", reply_markup=get_main_menu())

    elif data == 'elite_instant_report':
        # التقرير اللحظي (يحسب كل شيء حتى هذه اللحظة)
        async with AsyncSessionLocal() as session:
            # جلب كافة الصفقات التي أغلقت (نخبة فقط)
            res = await session.execute(
                select(PaperTrade).where(PaperTrade.is_elite == True, PaperTrade.status != "OPEN")
            )
            trades = res.scalars().all()
            
            won = len([t for t in trades if t.status == "WON"])
            lost = len([t for t in trades if t.status == "LOST"])
            total_pnl = sum([t.pnl for t in trades])
            
            report = (
                f"📋 *التقرير اللحظي (حتى الآن)*\n"
                f"━━━━━━━━━━━━━━\n"
                f"✅ ناجحة: `{won}` | ❌ خاسرة: `{lost}`\n"
                f"💰 صافي الربح التراكمي: `{total_pnl:.2f}$`\n"
                f"━━━━━━━━━━━━━━\n"
                f"💡 تم حساب هذا التقرير في تمام الساعة: `{datetime.now().strftime('%H:%M')}`"
            )
            await query.edit_message_text(report, reply_markup=get_main_menu(), parse_mode='Markdown')

    elif data == 'report':
        # زر "تقرير التدريب والتعلم" (خاص بالتعلم الخفي فقط)
        async with AsyncSessionLocal() as session:
            # جلب آخر 5 صفقات "تعلم خفي" (ليست نخبة)
            res = await session.execute(
                select(PaperTrade).where(PaperTrade.is_elite == False, PaperTrade.status != "OPEN")
                .order_by(desc(PaperTrade.closed_at)).limit(5)
            )
            trades = res.scalars().all()
            
            text = "🧠 *سجل التعلم الخفي والتدريب*\n━━━━━━━━━━━━━━\n"
            if not trades:
                text += "▫️ لا توجد بيانات تدريب كافية حالياً."
            for t in trades:
                icon = "🔬" if t.status == "WON" else "📉"
                text += f"{icon} *{t.symbol}*: {t.result_reason or 'تحليل تلقائي'}\n"
            
            text += "\n💡 _هذه الصفقات لم يتم إرسالها كإشارات لضمان الجودة._"
            await query.edit_message_text(text, reply_markup=get_main_menu(), parse_mode='Markdown')

# --- إضافة معالج الرسائل النصية للتحكم في "التعلم الخفي" ---
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if text == "▶️ بدء التعلم الخفي":
        # هنا تضع كود تفعيل المحرك في ملف main.py أو config
        await update.message.reply_text("🚀 تم بدء محرك التعلم الخفي. النظام يراقب السوق الآن بصمت.")
        
    elif text == "⏸️ إيقاف التعلم الخفي":
        await update.message.reply_text("⏸️ تم إيقاف محرك التعلم. سيتم إنهاء الصفقات المفتوحة حالياً فقط.")
