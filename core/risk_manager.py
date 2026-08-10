import asyncio, logging
from datetime import datetime, timedelta
from core.config import settings
from services.redis_client import redis_client

log = logging.getLogger("risk")

class RiskManager:
    def __init__(self): self.r = redis_client

    async def start(self):
        while True: await asyncio.sleep(60)

    def can_open(self, sym):
        if not self.r: return True
        today = datetime.utcnow().strftime("%Y%m%d")
        key = lambda x: f"risk:{sym}:{today}:{x}"
        trades = int(self.r.get(key("trades")) or 0)
        consec = int(self.r.get(f"risk:{sym}:consec_loss") or 0)
        pnl    = float(self.r.get(key("pnl")) or 0)
        cool   = self.r.get(f"risk:{sym}:cooldown_until")
        if cool and datetime.utcnow()<datetime.fromisoformat(cool): return False,"cooldown"
        if trades>=settings.MAX_TRADES_PER_DAY: return False,"daily_limit"
        if consec>=settings.MAX_CONSECUTIVE_LOSS: return False,"consec_loss"
        if pnl<=-settings.MAX_DAILY_LOSS_PCT: return False,"daily_loss"
        return True,"ok"

    def on_close(self, sym, pnl_pct):
        if not self.r: return
        today = datetime.utcnow().strftime("%Y%m%d")
        k = lambda x: f"risk:{sym}:{today}:{x}"
        self.r.incrby(k("trades"),1)
        self.r.incrbyfloat(k("pnl"), round(pnl_pct,4))
        if pnl_pct<0:
            c=int(self.r.incr(f"risk:{sym}:consec_loss",1) or 1)
            until = datetime.utcnow()+timedelta(minutes=settings.COOLDOWN_MIN if c<2 else 180)
            self.r.set(f"risk:{sym}:cooldown_until", until.isoformat(), ex=86400)
            if c>=settings.MAX_CONSECUTIVE_LOSS:
                self.r.set(f"risk:{sym}:paused_until", (datetime.utcnow()+timedelta(hours=24)).isoformat(), ex=90000)
        else:
            self.r.set(f"risk:{sym}:consec_loss",0, ex=86400)
