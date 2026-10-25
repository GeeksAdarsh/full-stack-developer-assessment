import json
import time
from datetime import datetime, timezone

from emailqueue.celery_app import app
from emailqueue.rate_limit import SlidingWindowLimiter
from emailqueue.sender import PermanentEmailError, TransientEmailError, deliver
from emailqueue.settings import MAX_PROVIDER_FAILURES, RATE_LIMIT, RATE_WINDOW_MS
from emailqueue.store import get_redis

INBOX = "emailq:inbox"
DEAD = "emailq:dead"
DEAD_IDS = "emailq:dead_ids"
REQUEUES = "emailq:rate_requeues"

limiter = SlidingWindowLimiter(
    get_redis(),
    limit=RATE_LIMIT,
    window_ms=RATE_WINDOW_MS,
    prefix="emailq",
)


def _runs_key(job_id):
    return f"emailq:runs:{job_id}"


def _push_dead(client, job, reason):
    body = json.dumps(
        {
            "job": job,
            "reason": reason,
            "failed_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    pipe = client.pipeline()
    pipe.lpush(DEAD, body)
    pipe.sadd(DEAD_IDS, str(job["job_id"]))
    pipe.execute()


@app.task(bind=True, acks_late=True, reject_on_worker_lost=True)
def send_transactional_email(self, job):
    """Send one transactional email, or put it back.

    Rate-limit waits are a new message with a countdown. They do not
    touch the failure counter. If they did, a flash sale would burn
    max_retries while the job was only waiting for a free slot, and
    the mail would land in the dead letter without ever being sent.

    Provider failures use exponential backoff: 1s, 2s, 4s, 8s, 16s.
    After MAX_PROVIDER_FAILURES the payload is pushed to emailq:dead.
    """
    if not isinstance(job, dict) or "job_id" not in job:
        client = get_redis()
        _push_dead(client, {"job_id": "unknown", "raw": str(job)}, "bad payload")
        return "dead"

    client = get_redis()
    job_id = str(job["job_id"])

    if client.sismember(INBOX, job_id) or client.sismember(DEAD_IDS, job_id):
        return "already_done"

    allowed, wait_seconds = limiter.try_acquire(f"{job_id}:{time.time_ns()}")
    if not allowed:
        # Fail closed. No token, no send. The job goes back on the queue.
        client.incr(REQUEUES)
        send_transactional_email.apply_async((job,), countdown=wait_seconds)
        return "rate_limited"

    client.incr(_runs_key(job_id))
    try:
        deliver(client, job)
    except TransientEmailError:
        failures_key = f"emailq:failures:{job_id}"
        failures = int(client.incr(failures_key))
        if failures >= MAX_PROVIDER_FAILURES:
            _push_dead(client, job, "provider kept failing")
            return "dead"
        delay = min(60, 2 ** (failures - 1))
        send_transactional_email.apply_async((job,), countdown=delay)
        return "retry"
    except PermanentEmailError as exc:
        _push_dead(client, job, str(exc))
        return "dead"
    except Exception as exc:
        # Anything we did not plan for is still on the dead-letter list,
        # so a bug does not delete the job.
        _push_dead(client, job, f"unexpected: {exc}")
        return "dead"

    return "sent"
