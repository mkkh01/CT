import os
from typing import Optional, Dict, Any, List
from contextlib import contextmanager
import threading
import psycopg2
from psycopg2 import pool, extras
from loguru import logger
from config import settings

class DatabaseConnection:
    _instance: Optional["DatabaseConnection"] = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.db_url = settings.RAW_DATABASE_URL
        self._pool: Optional[pool.ThreadedConnectionPool] = None
        self._connected = False
        self._initialized = True

    def connect(self) -> bool:
        if self._connected and self._pool:
            return True
        try:
            self._pool = pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=10,
                dsn=self.db_url,
                connect_timeout=10
            )
            conn = self._pool.getconn()
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            self._pool.putconn(conn)
            self._connected = True
            logger.info("Database connected via Supabase Pooler")
            return True
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            self._connected = False
            return False

    def disconnect(self):
        if self._pool:
            self._pool.closeall()
            self._pool = None
            self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._pool is not None

    @contextmanager
    def get_connection(self):
        if not self.is_connected:
            self.connect()
        conn = None
        try:
            conn = self._pool.getconn()
            yield conn
            conn.commit()
        except Exception as e:
            if conn: conn.rollback()
            raise
        finally:
            if conn: self._pool.putconn(conn)

    @contextmanager
    def get_cursor(self, cursor_factory=None):
        with self.get_connection() as conn:
            cursor_factory = cursor_factory or extras.RealDictCursor
            with conn.cursor(cursor_factory=cursor_factory) as cur:
                yield cur

    def execute(self, query: str, params: Optional[tuple] = None, fetch: bool = False):
        with self.get_cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall() if fetch else None

_db_instance = None
def get_db():
    global _db_instance
    if _db_instance is None:
        _db_instance = DatabaseConnection()
    return _db_instance

def init_db():
    return get_db().connect()
