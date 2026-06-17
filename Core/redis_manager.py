import redis
import json
from config import REDIS_HOST, REDIS_PORT, REDIS_PASS, REDIS_SSL

class RedisManager:
    def __init__(self):
        # استخدام بروتوكول redis:// العادي وتجربة الاتصال بدون SSL
        redis_url = f"redis://:{REDIS_PASS}@{REDIS_HOST}:{REDIS_PORT}"
        self.client = redis.from_url(
            redis_url, 
            decode_responses=True
        )

    def set_data(self, key, value, ex=None):
        """حفظ البيانات في Redis مع إمكانية تحديد وقت انتهاء (expiry)"""
        try:
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            self.client.set(key, value, ex=ex)
        except Exception as e:
            print(f"❌ [REDIS ERROR] Failed to set {key}: {e}")

    def get_data(self, key):
        """جلب البيانات من Redis وتحويلها من JSON إذا لزم الأمر"""
        try:
            data = self.client.get(key)
            if data:
                try:
                    return json.loads(data)
                except json.JSONDecodeError:
                    return data
            return None
        except Exception as e:
            print(f"❌ [REDIS ERROR] Failed to get {key}: {e}")
            return None

    def delete_data(self, key):
        """حذف مفتاح من Redis"""
        try:
            self.client.delete(key)
        except Exception as e:
            print(f"❌ [REDIS ERROR] Failed to delete {key}: {e}")

# إنشاء نسخة وحيدة (Singleton) للاستخدام في كامل النظام
redis_client = RedisManager()
