import os
import fcntl
import sys
import logging

logger = logging.getLogger(__name__)

class ProcessLock:
    def __init__(self, lock_file="/tmp/ct_trading_bot.lock"):
        self.lock_file = lock_file
        self.fd = None

    def acquire(self):
        try:
            self.fd = open(self.lock_file, 'w')
            # Try to acquire an exclusive lock without blocking
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Write the current PID to the lock file
            self.fd.write(str(os.getpid()))
            self.fd.flush()
            logger.info(f"✅ [LOCK] Acquired process lock: {self.lock_file} (PID: {os.getpid()})")
            return True
        except (IOError, OSError):
            logger.error(f"❌ [LOCK] Another instance is already running. (Lock file: {self.lock_file})")
            if self.fd:
                self.fd.close()
            return False

    def release(self):
        if self.fd:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
                self.fd.close()
                if os.path.exists(self.lock_file):
                    os.remove(self.lock_file)
                logger.info("🔓 [LOCK] Released process lock.")
            except Exception as e:
                logger.error(f"❌ [LOCK] Error releasing lock: {e}")
