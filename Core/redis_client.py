import redis
import json
from loguru import logger
from config.settings import REDIS_HOST, REDIS_PORT, REDIS_PASSWORD, REDIS_URL

class RedisManager:
    def __init__(self):
        try:
            if REDIS_URL:
                self.client = redis.from_url(REDIS_URL, decode_responses=True)
            else:
                self.client = redis.Redis(
                    host=REDIS_HOST,
                    port=REDIS_PORT,
                    password=REDIS_PASSWORD,
                    decode_responses=True
                )
            self.client.ping()
            logger.info("Redis connected successfully.")
        except Exception as e:
            logger.error(f"Redis connection failed: {e}")
            self.client = None

    def set_cache(self, key, value, ex=None):
        if not self.client: return False
        try:
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            return self.client.set(key, value, ex=ex)
        except Exception as e:
            logger.error(f"Redis set error: {e}")
            return False

    def get_cache(self, key):
        if not self.client: return None
        try:
            val = self.client.get(key)
            try:
                return json.loads(val)
            except:
                return val
        except Exception as e:
            logger.error(f"Redis get error: {e}")
            return None

redis_client = RedisManager()
