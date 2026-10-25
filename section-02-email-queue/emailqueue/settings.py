import os


REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")

# 200 sends in any 60 second window. Tests override these with env vars.
RATE_LIMIT = int(os.environ.get("EMAIL_RATE_LIMIT", "200"))
RATE_WINDOW_MS = int(os.environ.get("EMAIL_RATE_WINDOW_MS", "60000"))

# Real provider failures, not rate-limit waits.
MAX_PROVIDER_FAILURES = int(os.environ.get("EMAIL_MAX_FAILURES", "5"))

QUEUE_NAME = os.environ.get("EMAIL_QUEUE_NAME", "emails")
