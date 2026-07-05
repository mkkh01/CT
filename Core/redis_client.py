import json
import redis
from config import UPSTASH_REDIS_REST_URL, UPSTASH_REDIS_REST_TOKEN

class RedisClient:
    def __init__(self):
        # استخدام بروتوكول Redis (TCP) المباشر بدلاً من REST لضمان التوافق
        # الرابط: secure-ringtail-87484.upstash.io
        # البورت الافتراضي لـ Upstash هو 6379
        self.redis = redis.Redis(
            host="secure-ringtail-87484.upstash.io",
            port=6379,
            password=UPSTASH_REDIS_REST_TOKEN,
            ssl=True,
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

redis_client = RedisClient()
