import os
from supabase import create_client, Client
from config.settings import SUPABASE_URL, SUPABASE_KEY
from loguru import logger

class SupabaseManager:
    def __init__(self):
        self.client: Client = None
        if SUPABASE_URL and SUPABASE_KEY:
            try:
                self.client = create_client(SUPABASE_URL, SUPABASE_KEY)
                logger.info("Supabase client initialized.")
            except Exception as e:
                logger.error(f"Failed to initialize Supabase: {e}")
        else:
            logger.warning("Supabase credentials missing. Supabase integration disabled.")

    def insert(self, table, data):
        if not self.client: return None
        try:
            return self.client.table(table).insert(data).execute()
        except Exception as e:
            logger.error(f"Supabase insert error in {table}: {e}")
            return None

    def query(self, table, query_params=None):
        if not self.client: return None
        try:
            return self.client.table(table).select("*").execute()
        except Exception as e:
            logger.error(f"Supabase query error in {table}: {e}")
            return None

supabase_manager = SupabaseManager()
