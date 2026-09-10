"""معالج بوت تيليغرام: /start + الأزرار الخمسة."""
from datetime import datetime, timezone
from . import config, db, notify
from .cache import cache
from .market import VisionMarket
from .notify import KEYBOARD, fmt_px, sym

_CLOSED_AR = {"TP": "🎯", "SL": "🛑", "TSL": "🔒", "TIME": "⏱️"}


def admin_id():
    return config.ADMIN_CHAT_ID or db.get_state("admin_chat_id", "")


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
            notify.send_text(chat, "اختر من الأزرار 👇", KEYBOARD)
    except Exception as e:
        db.log_event("ERR", f"bot update: {e}")
    return True


def _on_start(chat):
    adm = str(admin_id())
    if not adm:
        db.set_state("admin_chat_id", chat)
        db.log_event("INFO", f"admin registered: {chat}")
        notify.send_text(chat, "🦅 أهلاً بك في نظام FALCON!\nتم تسجيلك كمدير. اختر من الأزرار 👇", KEYBOARD)
    elif chat == adm:
        notify.send_text(chat, "🦅 نظام FALCON — اختر 👇", KEYBOARD)
    else:
        notify.send_text(chat, "⛔ هذا البوت خاص.", None)
    return True


def _on_callback(cb):
    chat = str(cb["message"]["chat"]["id"])
    mid = cb["message"]["message_id"]
    if chat != str(admin_id()):
        notify.answer_cb(cb["id"], "⛔ خاص")
        return True
    key = cb.get("data", "")
    render = {"open": render_open, "closed": render_closed, "perf": render_perf,
              "prices": render_prices, "cycle": render_cycle}.get(key)
    if render:
        try:
            text = render()
        except Exception as e:
            text = f"⚠️ خطأ: {e}"
        notify.edit_text(chat, mid, text, KEYBOARD)
    notify.answer_cb(cb["id"])
    return True


# ═══════════════ العروض الخمسة ═══════════════
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


def render_perf():
    d = db.get_stats("DAY")
    f = db.get_stats("FALCON")
    t = db.get_stats()
    eq = db.realized_equity()
    ref = config.BACKTEST_REF
    return ("📊 أداء النظام (ورقي حي):\n"
            f"💰 الرصيد: ${eq:,.1f} ({(eq / config.PAPER_EQUITY - 1) * 100:+.2f}%)\n\n"
            f"⚡ DAY (الحي): n={d['n']} | WR {d['wr']}% | PF {d['pf']} | {d['net']:+.1f}$\n"
            f"   ↩️ باك تست DAY: {ref['DAY']['n']} صفقة | WR {ref['DAY']['wr']}% | PF {ref['DAY']['pf']} | +{ref['DAY']['net']:,.0f}$\n"
            f"🦅 FALCON (الحي): n={f['n']} | WR {f['wr']}% | PF {f['pf']} | {f['net']:+.1f}$\n"
            f"   ↩️ باك تست FALCON: {ref['FALCON']['n']} صفقة | WR {ref['FALCON']['wr']}% | PF {ref['FALCON']['pf']} | +{ref['FALCON']['net']:,.0f}$\n\n"
            f"📦 الإجمالي الحي: n={t['n']} | WR {t['wr']}% | PF {t['pf']} | {t['net']:+.1f}$\n"
            "ℹ️ ملاحظة: كل نظام له مرجع باك تست مختلف — DAY سكالبينج فوزه عالٍ (77%)، "
            "FALCON تتبّع اتجاه فوزه أقل (49%) لكن أرباح صفقاته أكبر.")


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


def render_cycle():
    """لقطة حية محسوبة عند الضغط: نبض محركات حقيقي الآن + عدادات الآن + تشخيص آخر دورة."""
    import json
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    interval = config.SCAN_INTERVAL_SEC

    # ── نبض حي الآن (فحص حقيقي لحظة الضغط — ليس سجلاً محفوظاً) ──
    health = {}
    try:
        VisionMarket().price("BTCUSDT")
        health["binance"] = "ok"
    except Exception as e:
        health["binance"] = f"ERR {str(e)[:50]}"
    try:
        health["supabase"] = "ok" if db.health() else "ERR"
    except Exception as e:
        health["supabase"] = f"ERR {str(e)[:50]}"
    try:
        health["redis"] = "ok" if cache.ping() else "ERR"
    except Exception as e:
        health["redis"] = f"ERR {str(e)[:50]}"
    health["telegram"] = "no-token"
    if config.BOT_TOKEN:
        try:
            health["telegram"] = "ok" if notify.get_me() else "ERR"
        except Exception as e:
            health["telegram"] = f"ERR {str(e)[:50]}"
    hb = lambda k: "✅" if health[k] == "ok" else ("⏭️" if health[k] == "no-token" else "❌")

    lines = ["🔄 لقطة النظام الحية (محسوبة الآن عند الضغط):",
             f"🕐 {now.strftime('%H:%M:%S')} UTC",
             f"💓 المحركات الآن: Binance{hb('binance')} Supabase{hb('supabase')} Redis{hb('redis')} Telegram{hb('telegram')}"]
    bad = {k: v for k, v in health.items() if v not in ("ok", "no-token")}
    if bad:
        lines.append("🔴 تفاصيل الأعطال: " + " | ".join(f"{k}: {v}" for k, v in bad.items()))

    # ── عدادات حية الآن ──
    try:
        t = db.system_totals(today)
        eq = db.realized_equity()
        day_start = float(db.get_state("day_start", str(eq)) or eq)
        lines += [f"📦 الآن: مفتوحة {t['open_n']} | مغلقة {t['closed_n']} | صفقات اليوم {t['today_n']} | دورات مسجلة {t['cycles']}",
                  f"💰 الرصيد: ${eq:,.1f} | بدأ اليوم ${day_start:,.0f} | P&L اليوم: {eq - day_start:+.1f}$"]
        h = db.get_state("halted", "")
        lines.append(f"🛑 الإيقاف: {'⚠️ نشط (' + h + ')' if h else 'لا'}")
    except Exception as e:
        lines.append(f"⚠️ تعذر حساب العدادات الآن: {str(e)[:90]}")

    # ── آخر دورة مسجلة + هل الجدولة حية؟ ──
    c = db.last_cycle()
    lines.append("────────────")
    if c:
        ended = c["ended_at"]
        ago_min = (now - ended).total_seconds() / 60
        stale = ago_min * 60 > interval * 2.5
        ago_txt = f"منذ {ago_min:.0f} دقيقة" if ago_min >= 1 else f"منذ {ago_min * 60:.0f} ثانية"
        sched = f"✅ تعمل كل {interval}ث بنظامية" if not stale else "⚠️ الدورات متوقفة عن الجدول! (السيرفر؟)"
        lines += [f"⏰ آخر دورة: #{c['id']} @ {ended.strftime('%H:%M:%S')} UTC ({ago_txt})",
                  f"📅 الجدولة: {sched}",
                  f"⏱️ مدتها {c['duration_ms'] / 1000:.1f}ث | مسح DAY {c['scanned_day']} + FALCON {c['scanned_falcon']} | "
                  f"إشارات {c['signals']} | فتح {c['opened']} | إغلاق {c['closed']}"]
        rjd = c["reject_day"] if isinstance(c.get("reject_day"), dict) else json.loads(c.get("reject_day") or "{}")
        rjf = c["reject_falcon"] if isinstance(c.get("reject_falcon"), dict) else json.loads(c.get("reject_falcon") or "{}")
        errors = c["errors"] if isinstance(c.get("errors"), list) else json.loads(c.get("errors") or "[]")
        if rjd:
            lines.append("🚫 رفض DAY: " + "، ".join(f"{k}×{v}" for k, v in sorted(rjd.items(), key=lambda x: -x[1])[:4]))
        if rjf:
            lines.append("🚫 رفض FALCON: " + "، ".join(f"{k}×{v}" for k, v in sorted(rjf.items(), key=lambda x: -x[1])[:4]))
        if errors:
            lines.append("⚠️ أخطاء آخر دورة: " + " | ".join(str(e)[:90] for e in errors[:3]))
    else:
        lines.append("⚠️ لا دورات مسجلة إطلاقاً — السيرفر لم يبدأ بعد")

    # ── الأخطاء الداخلية المسجلة ──
    errs = db.recent_errors(3)
    lines.append("────────────")
    if errs:
        lines.append("🧾 آخر الأخطاء الداخلية:")
        for e in errs:
            lines.append(f"• {e['ts'].strftime('%H:%M')} — {str(e['msg'])[:110]}")
    else:
        lines.append("✨ لا أخطاء داخلية مسجلة")
    lines.append(f"⚙️ ورقي | حد يومي {config.DAY['max_per_day']}×/عملة | إيقاف {config.RISK['daily_loss_halt'] * 100:.0f}% يومي / {config.RISK['max_drawdown_halt'] * 100:.0f}% كلي")
    return "\n".join(lines)[:3800]
