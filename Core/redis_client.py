import json
import redis
import asyncio
import os
import logging
from config import REDIS_HOST, REDIS_PORT, REDIS_PASSWORD
from Core.utils import make_json_safe

logger = logging.getLogger("CT_Redis")

class RedisClient:
    def __init__(self):
        # التحديث لاستخدام Redis Cloud الجديد
        try:
            self.redis = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                password=REDIS_PASSWORD,
                ssl=False,
                decode_responses=True,
                socket_timeout=5
            )
            self.redis.ping()
            print("✅ [REDIS] Connected successfully.")
        except Exception as e:
            print(f"⚠️ [REDIS] Connection failed: {e}. Using local fallback.")
            self.redis = None
            
        self._locks = {}
        self._global_lock = asyncio.Lock()

    async def get_lock(self, key):
        async with self._global_lock:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()
            return self._locks[key]

    def set_data(self, key, data, ttl=None):
        try:
            # تحويل البيانات لتكون آمنة للـ JSON قبل الحفظ
            safe_data = make_json_safe(data)
            value = json.dumps(safe_data)
            
            if self.redis:
                self.redis.set(key, value, ex=ttl)
            else:
                with open(f"/tmp/local_{key}.json", "w") as f:
                    f.write(value)
        except Exception as e:
            logger.error(f"❌ [REDIS] Set Error for {key}: {e}")
            # Fallback to local file if Redis fails
            try:
                safe_data = make_json_safe(data)
                with open(f"/tmp/local_{key}.json", "w") as f:
                    json.dump(safe_data, f)
            except Exception as fe:
                logger.error(f"❌ [REDIS] Local Fallback Error for {key}: {fe}")

    def get_data(self, key):
        try:
            data = None
            if self.redis:
                data = self.redis.get(key)
            
            if data: 
                return json.loads(data)
        except Exception as e:
            logger.error(f"❌ [REDIS] Get Error for {key}: {e}")
        
        # Fallback to local file
        try:
            path = f"/tmp/local_{key}.json"
            if os.path.exists(path):
                with open(path, "r") as f:
                    return json.load(f)
        except Exception as fe:
            logger.error(f"❌ [REDIS] Local Get Fallback Error for {key}: {fe}")
        
        return None

    def delete_data(self, key):
        try:
            if self.redis:
                self.redis.delete(key)
            else:
                path = f"/tmp/local_{key}.json"
                if os.path.exists(path):
                    os.remove(path)
        except Exception as e:
            logger.error(f"❌ [REDIS] Delete Error for {key}: {e}")

    def get_api_usage(self):
        """إرجاع عدد طلبات API الحالية"""
        return self.get_data("binance_api_calls") or 0

redis_client = RedisClient()
