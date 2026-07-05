import json
from upstash_redis import Redis
from config import UPSTASH_REDIS_REST_URL, UPSTASH_REDIS_REST_TOKEN

class RedisClient:
    def __init__(self):
        # التأكد من استخدام الرابط الصحيح (REST API)
        url = UPSTASH_REDIS_REST_URL if UPSTASH_REDIS_REST_URL.startswith("http") else f"https://{UPSTASH_REDIS_REST_URL}"
        self.redis = Redis(url=url, token=UPSTASH_REDIS_REST_TOKEN)

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
