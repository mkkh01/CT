import logging
import sys

def setup_logger(name: str):
    """تهيئة نظام التدوين السجلي الاحترافي لعرض أحداث البوت بدقة"""
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        
        # تنسيق السجلات ليظهر الوقت، اسم الملف، والمرحلة البرمجية الحالية
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)
        
    return logger
