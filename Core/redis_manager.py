import json
import os
import time

class RedisManager:
    """
    نظام تخزين محلي ذكي (Smart Local Cache) 
    يعمل كبديل لـ Redis باستخدام ملفات /tmp لضمان الاستمرارية والسرعة.
    """
    def __init__(self):
        self.cache_dir = "/tmp/ct_cache"
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir, exist_ok=True)

    def _get_path(self, key):
        return os.path.join(self.cache_dir, f"{key}.json")

    def set_data(self, key, value, ex=None):
        """حفظ البيانات محلياً مع دعم وقت الانتهاء"""
        try:
            path = self._get_path(key)
            data = {
                "value": value,
                "expiry": time.time() + ex if ex else None
            }
            with open(path, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            print(f"❌ [CACHE ERROR] Failed to set {key}: {e}")

    def get_data(self, key):
        """جلب البيانات والتحقق من صلاحيتها"""
        try:
            path = self._get_path(key)
            if not os.path.exists(path):
                return None
            
            with open(path, 'r') as f:
                data = json.load(f)
            
            # التحقق من وقت الانتهاء
            if data["expiry"] and time.time() > data["expiry"]:
                os.remove(path)
                return None
                
            return data["value"]
        except Exception as e:
            # في حال وجود خطأ في القراءة، نعتبر البيانات غير موجودة
            return None

    def delete_data(self, key):
        """حذف مفتاح الكاش"""
        try:
            path = self._get_path(key)
            if os.path.exists(path):
                os.remove(path)
        except Exception as e:
            print(f"❌ [CACHE ERROR] Failed to delete {key}: {e}")

# تصدير النسخة الموحدة لضمان التوافق مع بقية الكود دون تعديله
redis_client = RedisManager()
