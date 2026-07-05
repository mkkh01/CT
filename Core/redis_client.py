import json
import redis
from config import REDIS_HOST, REDIS_PORT, REDIS_PASSWORD

class RedisClient:
    def __init__(self):
        # التحديث لاستخدام Redis Cloud الجديد
        # ملاحظة: تم تعطيل SSL لأن بعض خطط Redis Cloud المجانية لا تدعمه أو قد يسبب تعارضاً في النسخ
        self.redis = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            password=REDIS_PASSWORD,
            ssl=False,
            decode_responses=True,
            socket_timeout=5
        )

    def set_data(self, key, data, ttl=None):
        try:
            value = json.dumps(data)
            self.redis.set(key, value, ex=ttl)
        except Exception as e:
            print(f"❌ [REDIS] Set Error for {key}: {e}")
            # Fallback to local file if Redis fails
            try:
                with open(f"/tmp/local_{key}.json", "w") as f:
                    json.dump(data, f)
            except: pass

    def get_data(self, key):
        try:
            data = self.redis.get(key)
            if data: return json.loads(data)
        except Exception as e:
            print(f"❌ [REDIS] Get Error for {key}: {e}")
        
        # Fallback to local file
        try:
            with open(f"/tmp/local_{key}.json", "r") as f:
                return json.load(f)
        except: return None

    def delete_data(self, key):
        try:
            self.redis.delete(key)
        except Exception as e:
            print(f"❌ [REDIS] Delete Error for {key}: {e}")

    def get_api_usage(self):
        """إرجاع عدد طلبات API الحالية"""
        return self.get_data("binance_api_calls") or 0

redis_client = RedisClient()
