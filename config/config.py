# config/config.py
from . import main_config

class ConfigManager:
    def __init__(self):
        self.settings = main_config
        self.constants = None
        self.env = None

    def validate(self):
        if self.settings and hasattr(self.settings, 'validate_config'):
            return self.settings.validate_config()
        return True

    def __getattr__(self, name):
        # Proxy to main_config if not found here
        if self.settings and hasattr(self.settings, name):
            return getattr(self.settings, name)
        raise AttributeError(f"'ConfigManager' object has no attribute '{name}'")

config = ConfigManager()
