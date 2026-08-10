import asyncio, logging, hashlib, json
from datetime import datetime
from core.config import settings
from services.supabase_client import supabase

log = logging.getLogger("signals")

class SignalGenerator:
    def __init__(self): self.last = {}

    async def start(self, engine, risk, tg):
        while True:
            await engine.ready.wait()
            for sym in settings.SYMBOLS:
                try:
                    r = engine.check(sym)
                    if not r: continue
                    ok,reason = risk.can_open(sym)
                    if not ok:
                        log.info("⛔ %s blocked: %s", sym, reason)
                        continue
                    sig_hash = hashlib.md5(f"{sym}:{r['price']:.4f}:{datetime.utcnow().strftime('%Y%m%d%H')}".encode()).hexdigest()
                    if sig_hash in self.last and (datetime.utcnow()-self.last[sig_hash]).total_seconds()<600: continue
                    self.last[sig_hash]=datetime.utcnow()
                    entry=r["price"]
                    payload={
                        "user_id":"system", "symbol":sym, "trigger_price":entry,
                        "tp_price":round(entry*1.01,8), "sl_price":round(entry*0.996,8),
                        "tf_1d_pass":True,"tf_4h_pass":True,"tf_1h_pass":True,
                        "ob_zone":list(r["ob"]),"fvg_zone":list(r["fvg"]),
                        "rsi_4h":r["rsi4h"],"rsi_1h":r["rsi1h"],"atr_pct":r["atr_pct"],
                        "in_trading_hours":True,"signal_hash":sig_hash,"status":"NEW",
                    }
                    if supabase:
                        try: supabase.table("trading_signals").insert(payload).execute()
                        except Exception as ex: log.warning("db err %s",ex)
                    msg = (f"🟢 BUY SIGNAL — {sym}\n"
                           f"Entry: {entry:.4f}\nTP 1%: {entry*1.01:.4f}\nSL -0.4%: {entry*0.996:.4f}\n"
                           f"RSI 4H/1H: {r['rsi4h']:.1f}/{r['rsi1h']:.1f}\nATR%: {r['atr_pct']:.2f}")
                    log.info(msg)
                    await tg.send_admin(msg)
                except Exception as ex:
                    log.exception("signal err %s", ex)
            await asyncio.sleep(60)
