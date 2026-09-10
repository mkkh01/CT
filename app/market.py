"""بيانات السوق من Binance Vision العامة (بدون مفاتيح، بلا حظر جغرافي)."""
import json
import requests
import pandas as pd


class VisionMarket:
    BASE = "https://data-api.binance.vision"

    def __init__(self):
        self.sess = requests.Session()

    def klines(self, symbol, interval, limit=300):
        r = self.sess.get(f"{self.BASE}/api/v3/klines",
                          params={"symbol": symbol, "interval": interval, "limit": limit},
                          timeout=20)
        r.raise_for_status()
        df = pd.DataFrame(r.json(),
                          columns=["open_time", "open", "high", "low", "close", "volume",
                                   "ct", "qv", "tr", "tb", "tq", "ig"])
        df = df[["open_time", "open", "high", "low", "close", "volume"]].astype(float)
        df["open_time"] = pd.to_datetime(df["open_time"].astype("int64"), unit="ms", utc=True)
        return df

    def price(self, symbol):
        r = self.sess.get(f"{self.BASE}/api/v3/ticker/price",
                          params={"symbol": symbol}, timeout=10)
        r.raise_for_status()
        return float(r.json()["price"])

    def prices(self, symbols):
        """أسعار دفعة واحدة (مع fallback فردي)."""
        try:
            r = self.sess.get(f"{self.BASE}/api/v3/ticker/price",
                              params={"symbols": json.dumps(list(symbols))}, timeout=15)
            r.raise_for_status()
            return {x["symbol"]: float(x["price"]) for x in r.json()}
        except Exception:
            out = {}
            for s in symbols:
                try:
                    out[s] = self.price(s)
                except Exception:
                    pass
            return out
