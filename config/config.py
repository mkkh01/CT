from . import settings
from . import constants
from . import env

class ConfigManager:
    def __init__(self):
        self.settings = settings
        self.constants = constants
        self.env = env

    def validate(self):
        return self.settings.validate_config()

config = ConfigManager()
