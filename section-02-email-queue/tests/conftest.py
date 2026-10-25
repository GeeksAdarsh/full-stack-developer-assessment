# Test settings. Loaded before the Celery app so the worker we spawn
# and the assertions use the same limit.
#
# Production is 200 per 60s. Here the window is 1 second and the cap
# is 20, so 500 jobs can finish without waiting out a real minute.
import os

os.environ["REDIS_URL"] = "redis://127.0.0.1:6379/1"
os.environ["EMAIL_RATE_LIMIT"] = "20"
os.environ["EMAIL_RATE_WINDOW_MS"] = "1000"
os.environ["EMAIL_QUEUE_NAME"] = "emails_test"
os.environ["EMAIL_MAX_FAILURES"] = "5"
os.environ["PYTHONUNBUFFERED"] = "1"
