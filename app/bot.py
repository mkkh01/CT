"""معالج بوت تيليغرام: /start + الأزرار الخمسة."""
from datetime import datetime, timezone
from . import config, db, notify
from .cache import cache
from .market import VisionMarket
from .notify import KEYBOARD, fmt_px, sym

_CLOSED_AR = {"TP": "🎯", "SL": "🛑", "TSL": "🔒", "TIME": "⏱️"}


def admin_id():
    # Chat ID الذي سجله المستخدم عبر /start هو المرجع الفعلي؛
    # قيمة البيئة تبقى fallback فقط إذا لم يوجد تسجيل في قاعدة البيانات.
    return db.get_state("admin_chat_id", "") or config.ADMIN_CHAT_ID


def handle_update(up):
    try:
        if "callback_query" in up:
            return _on_callback(up["callback_query"])
        msg = up.get("message", {})
        text = (msg.get("text") or "").strip()
        chat = str(msg.get("chat", {}).get("id", ""))
        if text.startswith("/start"):
            return _on_start(chat)
        if chat and chat == str(admin_id()):
            ok, result = notify.send_text(chat, "اختر من الأزرار 👇", KEYBOARD)
            print(f"[telegram-message] chat={chat} ok={ok} result={str(result)[:240]}", flush=True)
    except Exception as e:
        print(f"[telegram-update-error] {e}", flush=True)
        db.log_event("ERR", f"bot update: {e}")
    return True


def _on_start(chat):
    adm = str(admin_id())
    if not adm:
        db.set_state("admin_chat_id", chat)
        db.log_event("INFO", f"admin registered: {chat}")
        ok, result = notify.send_text(chat, "🦅 أهلاً بك في نظام FALCON!\nتم تسجيلك كمدير. اختر من الأزرار 👇", KEYBOARD)
    elif chat == adm:
        ok, result = notify.send_text(chat, "🦅 نظام FALCON — اختر 👇", KEYBOARD)
    else:
        ok, result = notify.send_text(chat, "⛔ هذا البوت خاص.", None)
    print(f"[telegram-start] chat={chat} admin={adm or 'registered'} ok={ok} result={str(result)[:240]}", flush=True)
    return True


def _on_callback(cb):
    chat = str(cb["message"]["chat"]["id"])
    mid = cb["message"]["message_id"]
    if chat != str(admin_id()):
        notify.answer_cb(cb["id"], "⛔ خاص")
        return True
    key = cb.get("data", "")
    render = {"open": render_open, "closed": render_closed, "perf": render_perf,
              "prices": render_prices, "cycle": render_cycle, "home": render_home}.get(key)
    if render:
        try:
            text = render()
        except Exception as e:
            text = f"⚠️ خطأ: {e}"
        notify.edit_text(chat, mid, text, KEYBOARD)
    notify.answer_cb(cb["id"])
    return True


# ═══════════════ العروض الخمسة ═══════════════
def render_home():
    return ("🦅 CT — FALCON Paper Trading\n"
            "لوحة التحكم الحية\n\n"
            "اختر القسم المطلوب من الأزرار أدناه.\n"
            "كل عرض يُحسب عند الضغط ويعكس الحالة الحالية للنظام.")


def render_open():
    pos = db.open_positions()
    if not pos:
        return "📌 لا صفقات مفتوحة حالياً.\n(طبيعي — النظامان انتقائيان)"
    pxs = {}
    try:
        pxs = VisionMarket().prices([p["symbol"] for p in pos])
    except Exception:
        pass
    lines = [f"📌 المفتوحة ({len(pos)}):"]
    for p in pos:
        cur = pxs.get(p["symbol"])
        if cur:
            upl = p["side"] * (cur - float(p["entry"])) * float(p["qty"])
            upl_s = f" | الآن {fmt_px(cur)} ({'+' if upl >= 0 else ''}{upl:.2f}$)"
        else:
            upl_s = ""
        leg = f"{p['leg']}" if p.get("leg") else ""
        lines.append(f"• {sym(p['symbol'])} {'🟢' if p['side'] == 1 else '🔴'}{leg} "
                     f"{p['system']} @ {fmt_px(p['entry'])}{upl_s}\n"
                     f"  🎯{fmt_px(p['tp'])} 🛑{fmt_px(p['sl'])}")
    return "\n".join(lines)[:3800]


def render_closed():
    rows = db.recent_closed(10)
    if not rows:
        return "📋 لا صفقات مغلقة بعد."
    lines = ["📋 آخر المغلقة:"]
    for t in rows:
        e = "✅" if t["net"] >= 0 else "❌"
        leg = f"{t['leg']}" if t.get("leg") else ""
        lines.append(f"{e} {sym(t['symbol'])}{leg} {'+' if t['net'] >= 0 else ''}{t['net']}$ "
                     f"(R={t['r']}) {_CLOSED_AR.get(t['reason'], t['reason'])}")
    return "\n".join(lines)[:3800]


def _live_health():
    """فحوصات حقيقية لحظة الضغط، لا تعتمد على لقطة محفوظة."""
    health = {}
    try:
        VisionMarket().price("BTCUSDT")
        health["Binance"] = "ok"
    except Exception as e:
        health["Binance"] = f"ERR {str(e)[:80]}"
    try:
        health["Supabase"] = "ok" if db.health() else "ERR"
    except Exception as e:
        health["Supabase"] = f"ERR {str(e)[:80]}"
    try:
        health["Redis"] = "ok" if cache.ping() else "ERR"
    except Exception as e:
        health["Redis"] = f"ERR {str(e)[:80]}"
    if not config.BOT_TOKEN:
        health["Telegram"] = "no-token"
    else:
        try:
            health["Telegram"] = "ok" if notify.get_me() else "ERR"
        except Exception as e:
            health["Telegram"] = f"ERR {str(e)[:80]}"
    return health


def _health_line(health):
    def mark(value):
        return "✅" if value == "ok" else ("⏭️" if value == "no-token" else "❌")
    return " ".join(f"{key}{mark(value)}" for key, value in health.items())


def _current_errors(c, health, stale=False):
    """الأخطاء الحالية فقط: فحص الآن + آخر دورة + توقف الجدولة الآن."""
    errors = [f"{key}: {value}" for key, value in health.items()
              if value not in ("ok", "no-token")]
    if c:
        raw = c.get("errors") or []
        if isinstance(raw, str):
            try:
                import json
                raw = json.loads(raw)
            except Exception:
                raw = [raw]
        errors.extend(str(error) for error in raw if error)
    if stale:
        errors.append("scheduler: لا توجد دورة حديثة ضمن المهلة")
    return errors


def render_perf():
    """أداء حي محسوب عند الضغط، مع الحالة الحالية لا سجل تاريخي."""
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    health = _live_health()
    d = db.get_stats("DAY")
    f = db.get_stats("FALCON")
    t = db.get_stats()
    eq = db.realized_equity()
    totals = db.system_totals(today)
    c = db.last_cycle()
    ref = config.BACKTEST_REF
    lines = ["📊 أداء النظام — لقطة حية محسوبة الآن:",
             f"🕐 {now.strftime('%H:%M:%S')} UTC | 💓 {_health_line(health)}",
             f"⚙️ الجدولة: {'تعمل كل ' + str(config.SCAN_INTERVAL_SEC) + 'ث' if config.RUN_SCHEDULER else 'متوقفة'}",
             f"📦 الصفقات المفتوحة: {totals['open_n']} | الصفقات المغلقة: {totals['closed_n']}",
             f"💰 الرصيد: ${eq:,.1f} | P&L الحالي: {(eq - config.PAPER_EQUITY):+.2f}$ | صفقات اليوم: {totals['today_n']}",
             f"🛡️ المخاطر: حد متزامن {config.RISK['max_concurrent']} | خسارة يومية {config.RISK['daily_loss_halt'] * 100:.0f}% | تراجع كلي {config.RISK['max_drawdown_halt'] * 100:.0f}% | الإيقاف: {db.get_state('halted', '') or 'لا'}",
             "",
             f"⚡ DAY حي: فوز {d['wins']} | خسارة {d['losses']} | WR {d['wr']}% | PF {d['pf']} | PnL {d['net']:+.2f}$",
             f"   ↩️ مرجع DAY: {ref['DAY']['n']} | WR {ref['DAY']['wr']}% | PF {ref['DAY']['pf']} | +{ref['DAY']['net']:,.0f}$",
             f"🦅 FALCON حي: فوز {f['wins']} | خسارة {f['losses']} | WR {f['wr']}% | PF {f['pf']} | PnL {f['net']:+.2f}$",
             f"   ↩️ مرجع FALCON: {ref['FALCON']['n']} | WR {ref['FALCON']['wr']}% | PF {ref['FALCON']['pf']} | +{ref['FALCON']['net']:,.0f}$",
             f"📊 الإجمالي الحي: فوز {t['wins']} | خسارة {t['losses']} | WR {t['wr']}% | PF {t['pf']} | PnL {t['net']:+.2f}$",
             f"🗄️ التخزين: PostgreSQL | 📡 التغذية الحية: مفعّلة | 🔁 الفحص الآلي: {'مفعّل' if config.RUN_SCHEDULER else 'متوقف'}"]
    stale = True
    if c:
        age = max(0, (now - c["ended_at"]).total_seconds())
        stale = age > config.SCAN_INTERVAL_SEC * 2.5
        lines.append(f"🔄 آخر دورة #{c['id']}: منذ {age:.0f}ث | {c['duration_ms'] / 1000:.1f}ث | إشارات {c['signals']} | فتح {c['opened']} | إغلاق {c['closed']}")
        lines.append(f"   مسح DAY {c['scanned_day']} + FALCON {c['scanned_falcon']} | رفض DAY {c['reject_day']} | رفض FALCON {c['reject_falcon']}")
    errors = _current_errors(c, health, stale)
    lines.append("⚠️ الأخطاء الحالية: " + " | ".join(errors[:6]) if errors else "✅ لا أخطاء حالية")
    return "\n".join(lines)[:3800]


def render_prices():
    out, missing = [], []
    for s in config.ALL_SYMBOLS:
        v = cache.get(f"ct:px:{s}")
        if v:
            out.append(f"{sym(s)}: {fmt_px(float(v))}")
        else:
            missing.append(s)
    if missing:
        try:
            fresh = VisionMarket().prices(missing)
            for s, v in fresh.items():
                cache.set(f"ct:px:{s}", v, ex=300)
                out.append(f"{sym(s)}: {fmt_px(v)}")
        except Exception:
            pass
    now = datetime.now(timezone.utc).strftime("%H:%M")
    return f"💰 الأسعار الحية ({now} UTC):\n" + "\n".join(sorted(out)[:40]) if out else "⚠️ لا أسعار متاحة الآن."


def _reason_label(key):
    return {
        "vol": "حجم التداول غير كافٍ",
        "adx": "قوة الاتجاه غير مناسبة",
        "no-trigger": "لم يتحقق محفز الدخول",
        "no-breakout": "لا يوجد اختراق",
        "regime-bear": "السوق في اتجاه هابط",
        "risk-size": "حجم المخاطرة غير مناسب",
        "risk-max-concurrent": "تم بلوغ الحد الأقصى للمراكز",
        "anti-double": "توجد صفقة للنظام والعملة نفسها",
    }.get(key, key)


def _reason_lines(title, reasons):
    lines = [title]
    if not reasons:
        lines.append("• لا توجد حالات رفض")
        return lines
    for key, count in sorted(reasons.items(), key=lambda item: -item[1]):
        lines.append(f"• {_reason_label(key)}: {count}")
    return lines


def render_cycle():
    """Samurai Cycle: تقرير حي واضح، بلا سجل أخطاء تاريخي."""
    import json
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    interval = config.SCAN_INTERVAL_SEC
    health = _live_health()
    c = db.last_cycle()
    lines = ["🔄 Samurai Cycle — الحالة الحية", ""]

    if c:
        cycle_health = c.get("health") if isinstance(c.get("health"), dict) else json.loads(c.get("health") or "{}")
        metrics = {key: int(cycle_health.get(key, 0) or 0) for key in (
            "signals_day", "signals_falcon", "opened_day", "opened_falcon",
            "closed_day", "closed_falcon")}
        ended = c["ended_at"]
        age = max(0, (now - ended).total_seconds())
        stale = age > interval * 2.5
        if not config.RUN_SCHEDULER:
            status = "🔴 متوقفة — الفحص الآلي معطل"
        elif stale:
            status = "🟠 متأخرة — آخر دورة تجاوزت الموعد المتوقع"
        else:
            status = "🟢 تعمل بشكل طبيعي"
        next_in = max(0, interval - age)
        next_text = "خلال أقل من دقيقة" if next_in < 60 else f"خلال {next_in / 60:.0f} دقيقة"
        ago = "لحظات" if age < 5 else f"{age:.0f} ثانية"
        lines.extend([
            f"{status}",
            f"🕐 آخر تحديث: {now.strftime('%H:%M:%S')} UTC",
            f"⏱️ آخر دورة: #{c['id']}",
            f"⌛ انتهت منذ: {ago}",
            f"⚡ مدة التنفيذ: {c['duration_ms'] / 1000:.1f} ثانية",
            f"⏰ الجدولة التالية: {next_text}",
            "",
            "━━━━━━━━━━━━━━",
            "🔍 نتيجة الفحص الأخير",
            "",
            "⚡ FALCON-DAY",
            f"• العملات المفحوصة: {c['scanned_day']}",
            f"• الإشارات: {metrics['signals_day']}",
            f"• الصفقات المفتوحة: {metrics['opened_day']}",
            f"• الصفقات المغلقة: {metrics['closed_day']}",
            "",
            "🦅 FALCON",
            f"• العملات المفحوصة: {c['scanned_falcon']}",
            f"• الإشارات: {metrics['signals_falcon']}",
            f"• الصفقات المفتوحة: {metrics['opened_falcon']}",
            f"• الصفقات المغلقة: {metrics['closed_falcon']}",
            "",
            "📊 إجمالي نتيجة الدورة",
            f"• الإشارات: {c['signals']}",
            f"• الصفقات المفتوحة: {c['opened']}",
            f"• الصفقات المغلقة: {c['closed']}",
            "",
            "━━━━━━━━━━━━━━",
            "📌 لماذا لم تُفتح صفقة؟",
        ])
        rjd = c["reject_day"] if isinstance(c.get("reject_day"), dict) else json.loads(c.get("reject_day") or "{}")
        rjf = c["reject_falcon"] if isinstance(c.get("reject_falcon"), dict) else json.loads(c.get("reject_falcon") or "{}")
        lines.extend(_reason_lines("⚡ FALCON-DAY", rjd))
        lines.append("")
        lines.extend(_reason_lines("🦅 FALCON", rjf))
        raw_errors = c.get("errors") or []
        if isinstance(raw_errors, str):
            try:
                raw_errors = json.loads(raw_errors)
            except Exception:
                raw_errors = [raw_errors]
    else:
        stale = True
        raw_errors = ["لا توجد دورة مسجلة بعد"]
        lines.extend(["🟠 في انتظار أول دورة", f"🕐 آخر تحديث: {now.strftime('%H:%M:%S')} UTC"])

    lines.extend(["", "━━━━━━━━━━━━━━", "💓 حالة المحركات",
                  f"Binance {'✅' if health['Binance'] == 'ok' else '❌'}   Supabase {'✅' if health['Supabase'] == 'ok' else '❌'}",
                  f"Redis {'✅' if health['Redis'] == 'ok' else '❌'}     Telegram {'✅' if health['Telegram'] == 'ok' else '❌'}",
                  "", "🧾 الأخطاء الحالية"])
    current_errors = _current_errors(c, health, stale)
    # لا نكرر تنبيه stale كخطأ إذا كانت الجدولة متوقفة عمدًا.
    if not config.RUN_SCHEDULER:
        current_errors = [e for e in current_errors if "لا توجد دورة حديثة" not in e]
    if current_errors:
        lines.extend(f"❌ {str(error)[:150]}" for error in current_errors[:8])
    else:
        lines.append("✅ لا توجد أخطاء حالية")
    return "\n".join(lines)[:3900]
