"""Sliding-window rate limiter.

One Lua script does the whole check. Redis runs that script by itself,
so two workers cannot both sneak in when only one slot is left.

Keys:
  {prefix}:window    sorted set of sends still inside the window
  {prefix}:accepted  sorted set of every send we allowed (not trimmed)

The second key is there so a test can prove the cap after the window
has moved on. Production can expire it if the log gets noisy.
"""

import time

from redis.exceptions import RedisError

# ARGV: now_ms, window_ms, limit, member
# Returns {allowed, count, wait_ms}
LUA = """
local key = KEYS[1]
local log_key = KEYS[2]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]

redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
local count = redis.call('ZCARD', key)

if count < limit then
    redis.call('ZADD', key, now, member)
    redis.call('ZADD', log_key, now, member)
    redis.call('PEXPIRE', key, window + 1000)
    return {1, count + 1, 0}
end

local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
local oldest_score = tonumber(oldest[2])
local wait_ms = (oldest_score + window) - now
if wait_ms < 1 then
    wait_ms = 1
end
return {0, count, wait_ms}
"""


class SlidingWindowLimiter:
    def __init__(self, client, limit, window_ms, prefix="emailq"):
        self.redis = client
        self.limit = int(limit)
        self.window_ms = int(window_ms)
        self.window_key = f"{prefix}:window"
        self.log_key = f"{prefix}:accepted"
        self._script = client.register_script(LUA)

    def try_acquire(self, member, now_ms=None):
        """Return (allowed, retry_after_seconds).

        On a Redis error we return allowed=False. The caller must not send.
        """
        if now_ms is None:
            now_ms = int(time.time() * 1000)
        try:
            result = self._script(
                keys=[self.window_key, self.log_key],
                args=[now_ms, self.window_ms, self.limit, member],
            )
        except RedisError:
            return False, 1.0

        allowed = int(result[0]) == 1
        wait_ms = int(result[2])
        # Celery countdown is in seconds. Round up so we don't wake
        # the job before a slot actually exists, and never use 0.
        # A 0 countdown just spins the worker.
        wait_seconds = max(1, (wait_ms + 999) // 1000)
        return allowed, float(wait_seconds)
