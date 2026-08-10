import redis as _r
from core.config import settings
redis_client = _r.Redis.from_url(settings.REDIS_URL, decode_responses=True) if settings.REDIS_URL else None
