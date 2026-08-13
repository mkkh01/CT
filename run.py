import logging
import os
import threading
import time
from app.main import create_app

# Force production logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("CT_BOOT")

logger.info("Initializing Stable Entry Point...")

# The Flask application instance
app = create_app()

if __name__ == "__main__":
    # Local development mode
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
