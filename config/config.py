import sys
from pathlib import Path

# إضافة المسار الرئيسي للبحث عن config.py
sys.path.append(str(Path(__file__).parent.parent))

try:
    import config as main_config
except ImportError:
    import config as main_config

class ConfigManager:
    def __init__(self):
        self.settings = main_config
        self.constants = None # سيتم تحميله عند الحاجة
        self.env = None # تم إزالته

    def validate(self):
        return main_config.validate_config()

config = ConfigManager()
