import os
import sys
import logging

# Ensure the app directory is in the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.main import app
from waitress import serve

# Configure logging for waitress
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger('waitress')

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"Starting Waitress server on port {port}...")
    serve(app, host='0.0.0.0', port=port, threads=4, channel_timeout=120)
