import sys
import logging
from loguru import logger
from config.settings import LOG_LEVEL, DEBUG_MODE

def setup_logging():
    # Remove default handler
    logger.remove()
    
    # Standard output handler
    log_format = "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    
    logger.add(sys.stdout, format=log_format, level=LOG_LEVEL)
    
    # File handlers for different categories
    logger.add("logs/trading.log", rotation="10 MB", level="INFO", filter=lambda record: "trade" in record["message"].lower())
    logger.add("logs/ai_engine.log", rotation="10 MB", level="INFO", filter=lambda record: "ai" in record["message"].lower() or "model" in record["message"].lower())
    logger.add("logs/error.log", rotation="10 MB", level="ERROR")
    logger.add("logs/application.log", rotation="50 MB", level="INFO")

    if DEBUG_MODE:
        logger.add("logs/debug.log", rotation="10 MB", level="DEBUG")

    # Intercept standard logging
    class InterceptHandler(logging.Handler):
        def emit(self, record):
            try:
                level = logger.level(record.levelname).name
            except ValueError:
                level = record.levelno

            frame, depth = logging.currentframe(), 2
            while frame.f_code.co_filename == logging.__file__:
                frame = frame.f_back
                depth += 1

            logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())

    logging.basicConfig(handlers=[InterceptHandler()], level=0)
    logger.info(f"Logging initialized with level: {LOG_LEVEL}")

class MetricsCollector:
    def __init__(self):
        self.metrics = {}

    def record_metric(self, name, value):
        self.metrics[name] = value
        logger.debug(f"Metric recorded: {name} = {value}")

metrics = MetricsCollector()
