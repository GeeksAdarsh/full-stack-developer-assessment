import redis

from emailqueue.settings import REDIS_URL

_client = None


def get_redis():
    global _client
    if _client is None:
        _client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    return _client
