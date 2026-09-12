"""بيانات السوق من Binance العامة مع تخزين مؤقت وحدّ من محاولات الـ fallback."""
import json
import threading
import time

import pandas as pd
import requests


# الاستراتيجية تعمل على شموع مكتملة فقط؛ لذلك لا معنى لتحميل الشمعة نفسها كل دقيقة.
# تُحاذى مدة التخزين المؤقت مع حدود الشموع بدلاً من TTL ثابت قد يؤخر إشارة جديدة.
_INTERVAL_SECONDS = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "8h": 28800,
    "12h": 43200,
    "1d": 86400,
    "3d": 259200,
    "1w": 604800,
}
_PRICE_CACHE_TTL = 60.0
_CACHE_LOCK = threading.RLock()
_KLINES_CACHE = {}  # (symbol, interval) -> (expiry, dataframe)
_PRICE_CACHE = {}   # symbol -> (expiry, price)


def _candle_cache_expiry(interval, now=None):
    """أعد وقت انتهاء الكاش عند الحد الزمني التالي للشمعة."""
    now = time.time() if now is None else now
    period = _INTERVAL_SECONDS.get(interval)
    if not period:
        # لا نعرف محاذاة هذا الإطار، لذا نستخدم كاشاً قصيراً وآمناً.
        return now + 30.0
    # مهلة صغيرة تمنع تكرار الطلب إذا بدأ المسح قبل الحد بثوانٍ قليلة.
    # التأخير الأقصى لإشارة جديدة يظل دورة واحدة (60 ثانية افتراضياً).
    return (int(now) // period + 1) * period + 5.0


class VisionMarket:
    BASES = ("https://api.binance.us", "https://api.binance.me",
             "https://api-gcp.binance.com", "https://www.binance.com",
             "https://api2.binance.com", "https://api3.binance.com",
             "https://api4.binance.com", "https://data-api.binance.vision",
             "https://api.binance.com", "https://api1.binance.com")
    # إذا كان أول endpoint محجوباً، لا نعيد زيارته قبل كل طلب في كل دورة.
    _preferred_base = 0
    _base_lock = threading.Lock()

    def __init__(self):
        self.sess = requests.Session()
        self.sess.headers.update({"User-Agent": "CT-FALCON/1.0"})

    @classmethod
    def _base_order(cls):
        with cls._base_lock:
            start = cls._preferred_base
        return [(start + i) % len(cls.BASES) for i in range(len(cls.BASES))]

    @classmethod
    def _remember_base(cls, index):
        with cls._base_lock:
            cls._preferred_base = index

    def _get(self, path, **kwargs):
        last = None
        for index in self._base_order():
            base = self.BASES[index]
            try:
                r = self.sess.get(f"{base}{path}", **kwargs)
                if r.status_code == 200:
                    self._remember_base(index)
                    return r
                last = requests.HTTPError(f"{r.status_code} from {base}")
            except requests.RequestException as e:
                last = e
        raise last or requests.RequestException("Binance endpoints unavailable")

    def klines(self, symbol, interval, limit=300):
        """اجلب الشموع مرة واحدة لكل شمعة مكتملة وأعد نسخة آمنة من البيانات.

        الاستدعاءات الحالية تأتي كل 60 ثانية، بينما DAY يعتمد على 15m وFALCON
        على 4h و1d. قبل هذا الكاش كان نفس JSON (حتى 300 شمعة) يُحمّل في كل
        دورة؛ الآن يُعاد استخدامه حتى يتغير الإطار الزمني.
        """
        limit = int(limit)
        key = (symbol, interval)
        now = time.time()
        with _CACHE_LOCK:
            cached = _KLINES_CACHE.get(key)
            if cached and cached[0] > now and len(cached[1]) >= limit:
                return cached[1].tail(limit).copy()
            # عند انتهاء الكاش، حدّث بنفس الحجم الأكبر الموجود حتى لا يستبدل
            # طلب مدير الصفقات تاريخ المسح الكامل بطلب limit=3.
            fetch_limit = max(limit, len(cached[1]) if cached else 0)

        r = self._get("/api/v3/klines",
                       params={"symbol": symbol, "interval": interval, "limit": fetch_limit},
                       timeout=20)
        df = pd.DataFrame(r.json(),
                          columns=["open_time", "open", "high", "low", "close", "volume",
                                   "ct", "qv", "tr", "tb", "tq", "ig"])
        df = df[["open_time", "open", "high", "low", "close", "volume"]].astype(float)
        df["open_time"] = pd.to_datetime(df["open_time"].astype("int64"), unit="ms", utc=True)
        with _CACHE_LOCK:
            # خزّن الطلب الأكبر حتى يستفيد منه مدير الصفقات عند طلب limit صغير.
            current = _KLINES_CACHE.get(key)
            if not current or len(current[1]) <= len(df):
                _KLINES_CACHE[key] = (_candle_cache_expiry(interval), df)
            else:
                # طلب أصغر لا يجب أن يستبدل تاريخاً أكبر موجوداً.
                df = current[1]
        return df.tail(limit).copy()

    def price(self, symbol):
        now = time.time()
        with _CACHE_LOCK:
            cached = _PRICE_CACHE.get(symbol)
            if cached and cached[0] > now:
                return float(cached[1])
        r = self._get("/api/v3/ticker/price", params={"symbol": symbol}, timeout=10)
        value = float(r.json()["price"])
        with _CACHE_LOCK:
            _PRICE_CACHE[symbol] = (time.time() + _PRICE_CACHE_TTL, value)
        return value

    def prices(self, symbols):
        """أسعار دفعة واحدة، مع كاش قصير وfallback فردي عند الحاجة."""
        requested = list(dict.fromkeys(symbols))
        now = time.time()
        out = {}
        missing = []
        with _CACHE_LOCK:
            for symbol in requested:
                cached = _PRICE_CACHE.get(symbol)
                if cached and cached[0] > now:
                    out[symbol] = float(cached[1])
                else:
                    missing.append(symbol)

        if missing:
            try:
                r = self._get("/api/v3/ticker/price",
                              params={"symbols": json.dumps(missing)}, timeout=15)
                fresh = {x["symbol"]: float(x["price"]) for x in r.json()}
                with _CACHE_LOCK:
                    expiry = time.time() + _PRICE_CACHE_TTL
                    for symbol, value in fresh.items():
                        _PRICE_CACHE[symbol] = (expiry, value)
                out.update(fresh)
            except Exception:
                # لا نعيد ضرب كل endpoint بلا داعٍ؛ price() يشارك نفس الكاش.
                for symbol in missing:
                    try:
                        out[symbol] = self.price(symbol)
                    except Exception:
                        pass
        return {symbol: out[symbol] for symbol in requested if symbol in out}
