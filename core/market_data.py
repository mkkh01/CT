import asyncio, json, logging
import websockets
from core.config import settings

log = logging.getLogger("market")

def _s(sym: str):
    return sym.replace("/", "").lower()

class MarketData:
    def __init__(self):
        self.bars = {}
        self.price = {}

    async def start(self):
        while True:
            try:
                streams = "/".join(
                    f"{_s(s)}@kline_1h/{_s(s)}@kline_4h/{_s(s)}@kline_1d/{_s(s)}@trade"
                    for s in settings.SYMBOLS
                )
                url = f"wss://stream.binance.com:9443/stream?streams={streams}"
                log.info("🔌 Binance WebSocket connecting...")
                async with websockets.connect(url, ping_interval=30) as ws:
                    async for m in ws:
                        try:
                            d = json.loads(m).get("data", {})
                            if d.get("e") == "kline":
                                sym = d["s"].upper()
                                tf = d["k"]["i"]
                                k = d["k"]
                                row = [float(k["o"]), float(k["h"]), float(k["l"]), float(k["c"]), float(k["v"])]
                                self.bars.setdefault(sym, {}).setdefault(tf, [])
                                arr = self.bars[sym][tf]
                                if not arr or len(arr[-1]) != 6 or arr[-1][5] != k["t"]:
                                    arr.append(row + [k["t"]])
                                else:
                                    arr[-1] = row + [k["t"]]
                                if len(arr) > 300:
                                    arr.pop(0)
                                self.price[sym] = row[3]
                            elif d.get("e") == "trade":
                                self.price[d["s"].upper()] = float(d["p"])
                        except Exception as ex:
                            log.debug("Parse error: %s", ex)
            except Exception as ex:
                log.warning("🔌 WS reconnect in 3s — %s", ex)
                await asyncio.sleep(3)
