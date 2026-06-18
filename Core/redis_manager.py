
import json
import os
import time
import asyncio

class RedisManager:
    """
    نظام تخزين محلي ذكي (Smart Local Cache) مع دعم Double Buffer Cache
    يعمل كبديل لـ Redis باستخدام ملفات /tmp لضمان الاستمرارية والسرعة.
    """
    def __init__(self):
        self.cache_dir = "/tmp/ct_cache"
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir, exist_ok=True)
        self.buffer_lock = asyncio.Lock() # لضمان عدم تضارب الكتابة بين الـ buffers

    def _get_path(self, key, is_buffer=False):
        if is_buffer:
            return os.path.join(self.cache_dir, f"{key}_buffer.json")
        return os.path.join(self.cache_dir, f"{key}.json")

    async def set_data(self, key, value, ex=None):
        """حفظ البيانات محلياً في buffer ثم نقلها للـ active cache"""
        async with self.buffer_lock:
            try:
                buffer_path = self._get_path(key, is_buffer=True)
                active_path = self._get_path(key)
                
                data = {
                    "value": value,
                    "expiry": time.time() + ex if ex else None
                }
                
                # 1. الكتابة إلى الـ buffer
                with open(buffer_path, 'w') as f:
                    json.dump(data, f)
                
                # 2. نقل الـ buffer إلى الـ active cache (atomic swap)
                os.replace(buffer_path, active_path)
                
            except Exception as e:
                print(f"❌ [CACHE ERROR] Failed to set {key} with double buffer: {e}")

    def get_data(self, key):
        """جلب البيانات من الـ active cache والتحقق من صلاحيتها"""
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
            buffer_path = self._get_path(key, is_buffer=True)
            if os.path.exists(path):
                os.remove(path)
            if os.path.exists(buffer_path):
                os.remove(buffer_path)
        except Exception as e:
            print(f"❌ [CACHE ERROR] Failed to delete {key}: {e}")

# تصدير النسخة الموحدة لضمان التوافق مع بقية الكود دون تعديله
redis_client = RedisManager()
