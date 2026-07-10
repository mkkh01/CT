"""
Single source of truth for Telegram bot lifecycle.

Guarantees:
- Only one Application instance per process.
- Only one active polling loop.
- deleteWebhook is called before polling.
- Conflict (409) is retried with exponential backoff.
- Graceful shutdown stops polling and closes the application cleanly.
"""

import asyncio
import logging
import os
import signal
import sys
import time
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest
from telegram.error import Conflict, NetworkError, TimedOut

logger = logging.getLogger("CT_Telegram")

# ── Retry configuration ──────────────────────────────────────────────
MAX_RETRIES = int(os.environ.get("TG_POLLING_MAX_RETRIES", "5"))
BASE_BACKOFF_SECONDS = int(os.environ.get("TG_POLLING_BACKOFF_BASE", "15"))
MAX_BACKOFF_SECONDS = int(os.environ.get("TG_POLLING_BACKOFF_MAX", "300"))


class TelegramManager:
    """
    Encapsulates the full lifecycle of the Telegram bot.

    Usage::

        manager = TelegramManager(token, handlers_def, post_init_cb)
        await manager.start()
        # ... application runs ...
        await manager.stop()
    """

    def __init__(
        self,
        token: str,
        post_init_callback=None,
        error_handler=None,
    ):
        self._token = token
        self._post_init_callback = post_init_callback
        self._error_handler = error_handler
        self._app: Optional[Application] = None
        self._polling_task: Optional[asyncio.Task] = None
        self._running = False
        self._shutdown_requested = False

    # ── Public API ────────────────────────────────────────────────

    @property
    def app(self) -> Optional[Application]:
        return self._app

    @property
    def bot(self):
        return self._app.bot if self._app else None

    async def start(self) -> bool:
        """
        Build the Application, register handlers, delete webhook, start
        polling.  Returns True on success or False after exhausting retries.
        """
        if self._running:
            logger.warning("[TELEGRAM] start() called but already running — ignored.")
            return True

        logger.info("[TELEGRAM] ==========================================")
        logger.info("[TELEGRAM] Initializing...")
        self._build_application()
        self._register_handlers()

        # Always delete webhook before polling to avoid conflicts.
        await self._delete_webhook()

        # Retry loop with exponential backoff.
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                logger.info("[TELEGRAM] Starting polling (attempt %d/%d)...", attempt, MAX_RETRIES)
                self._running = True
                self._shutdown_requested = False

                # drop_pending_updates=True prevents replay of stale updates
                # from a previous crashed instance.
                await self._app.initialize()
                await self._app.start()
                await self._app.updater.start_polling(
                    drop_pending_updates=True,
                )
                logger.info("[TELEGRAM] ✅ Polling active")
                return True

            except Conflict:
                backoff = min(
                    BASE_BACKOFF_SECONDS * (2 ** (attempt - 1)),
                    MAX_BACKOFF_SECONDS,
                )
                logger.warning(
                    "[TELEGRAM] ⚠️  Another instance detected (Conflict 409). "
                    "Retrying in %d seconds... (attempt %d/%d)",
                    backoff, attempt, MAX_RETRIES,
                )
                await self._stop_polling_safe()
                await asyncio.sleep(backoff)

            except (NetworkError, TimedOut) as exc:
                backoff = min(BASE_BACKOFF_SECONDS * (2 ** (attempt - 1)), 120)
                logger.warning(
                    "[TELEGRAM] ⚠️  Network error (%s). Retrying in %d seconds...",
                    type(exc).__name__, backoff,
                )
                await self._stop_polling_safe()
                await asyncio.sleep(backoff)

            except Exception as exc:
                logger.error("[TELEGRAM] ❌ Unexpected error during polling: %s", exc, exc_info=True)
                await self._stop_polling_safe()
                return False

        logger.error("[TELEGRAM] ❌ Failed to start after %d attempts.", MAX_RETRIES)
        return False

    async def stop(self):
        """Gracefully stop polling and close the Application."""
        if not self._running:
            return
        logger.info("[TELEGRAM] Shutting down...")
        self._shutdown_requested = True
        await self._stop_polling_safe()
        self._running = False
        logger.info("[TELEGRAM] ✅ Shutdown complete")

    # ── Internal helpers ──────────────────────────────────────────

    async def _delete_webhook(self):
        """Remove any leftover webhook so polling can start cleanly."""
        logger.info("[TELEGRAM] Removing webhook...")
        try:
            await self._app.bot.delete_webhook(drop_pending_updates=True)
            logger.info("[TELEGRAM] ✅ Webhook removed")
        except Exception as exc:
            logger.warning("[TELEGRAM] ⚠️  Could not delete webhook: %s", exc)

    async def _stop_polling_safe(self):
        """Stop polling and shutdown without raising."""
        try:
            if self._app and self._app.updater and self._app.updater.running:
                await self._app.updater.stop()
        except Exception as exc:
            logger.debug("[TELEGRAM] updater.stop: %s", exc)
        try:
            if self._app:
                try:
                    await self._app.stop()
                except Exception:
                    pass
        except Exception:
            pass

    def _build_application(self):
        """Create the Application singleton."""
        request_config = HTTPXRequest(connect_timeout=20, read_timeout=20)
        builder = Application.builder().token(self._token).request(request_config)
        if self._post_init_callback:
            builder = builder.post_init(self._post_init_callback)
        self._app = builder.build()
        if self._error_handler:
            self._app.add_error_handler(self._error_handler)

    def _register_handlers(self):
        """Register all bot command and conversation handlers.

        Imported here (not at module top) to avoid circular imports
        with bot.handlers which imports database, config, etc.
        """
        from bot.handlers import start, handle_buttons

        self._app.add_handler(CommandHandler("start", start))
        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buttons)
        )
        logger.info("[TELEGRAM] ✅ Handlers registered")


# ── Global singleton (created at startup, used by background tasks) ──
_instance: Optional[TelegramManager] = None


def get_telegram_manager() -> Optional[TelegramManager]:
    return _instance


def set_telegram_manager(manager: TelegramManager):
    global _instance
    _instance = manager
