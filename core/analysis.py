import asyncio, logging
from datetime import datetime, time as dtime
import numpy as np
from core.config import settings
from core import indicators as ta

log = logging.getLogger("analysis")

def _tf(d, k):
    arr=d.get(k,[])
    if len(arr)<30: return None
    return [np.array([r[i] for r in arr]) for i in range(5)]  # O H L C V

def in_hours():
    now=datetime.utcnow().time()
    a=datetime.strptime(settings.TRADE_START_UTC,"%H:%M").time()
    b=datetime.strptime(settings.TRADE_END_UTC,"%H:%M").time()
    return a<=now<=b

class AnalysisEngine:
    def __init__(self): self.ready = asyncio.Event()

    async def start(self, market):
        while True:
            self.data = {}
            for sym in settings.SYMBOLS:
                bars = market.bars.get(sym,{})
                d1 = _tf(bars,"1d"); d4=_tf(bars,"4h"); d1h=_tf(bars,"1h")
                if not (d1 and d4 and d1h): continue
                self.data[sym] = {"1d":d1,"4h":d4,"1h":d1h,"last":market.price.get(sym)}
            self.ready.set()
            await asyncio.sleep(60)

    def check(self, sym):
        d=self.data.get(sym);
        if not d or not in_hours(): return None
        o1,h1,l1,c1,v1 = d["1d"]
        o4,h4,l4,c4,v4 = d["4h"]
        oh,hh,lh,ch,vh = d["1h"]

        # 1D filter
        e20_1=ta.ema(c1,20)[-1]; e50_1=ta.ema(c1,50)[-1]
        sl=ta.swing_low(l1,2); sh=ta.swing_high(h1,2)
        if not (e20_1>e50_1 and c1[-1]>e20_1 and len(sl)>=2 and len(sh)>=2): return None
        if not (sl[-1][1]>sl[-2][1] and sh[-1][1]>sh[-2][1]): return None
        if (np.max(h1[-7:])-np.min(l1[-7:]))/np.max(h1[-7:])>0.08: return None

        # 4H filter
        ob=ta.bullish_ob(o4,h4,l4,c4,v4)
        if not ob: return None
        P=d["last"] or c4[-1]
        if not (ob[0]*0.995 <= P <= ob[1]*1.005): return None
        fvg=ta.fvg(h4,l4)
        if not fvg: return None
        dist=(fvg[0]-P)/P*100
        if not (0.9<=dist<=1.3): return None
        r4=ta.rsi(c4,7)[-1]
        if not (28<=r4<=38): return None
        if np.mean(v4[-3:])>=np.mean(v4[-6:-3]): return None

        # 1H trigger
        if not ta.engulfing_bull(oh,ch): return None
        e20h=ta.ema(ch,20)[-1]
        if ch[-1]<=e20h: return None
        rh=ta.rsi(ch,7)[-1]
        if not (32<=rh<=52): return None
        if vh[-1]<1.7*np.mean(vh[-10:]): return None
        atr1h=ta.atr(hh,lh,ch,14)[-1]
        atrp=atr1h/ch[-1]*100
        if not (settings.MIN_ATR_PCT<=atrp<=settings.MAX_ATR_PCT): return None

        return {"symbol":sym,"price":float(P),"ob":ob,"fvg":fvg,"rsi4h":float(r4),"rsi1h":float(rh),"atr_pct":float(atrp)}
