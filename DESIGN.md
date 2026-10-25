# Queue design

The job is transactional email. The provider allows 200 sends in a minute. A flash sale can dump 2,000 requests on us in a few seconds. A worker can also die in the middle of a send. The queue has to hold the burst, stay under the cap, retry real failures, and not forget a job.

## What I picked

Celery, with Redis as the broker. The task is `send_transactional_email` in `section-02-email-queue/emailqueue/tasks.py`.

I looked at three shapes.

Celery + Redis is the one I know how to operate next to Django, and it already has the crash behaviour the brief asks about. `task_acks_late` and `task_reject_on_worker_lost` are real settings, not something I'd have to invent. The cost is that Celery has a lot of knobs, and on Windows you have to run `--pool=solo` because prefork doesn't work there. I also couldn't use Celery's own `autoretry_for` for the rate limit. More on that below.

Django Q keeps the queue in the database, which is one less service. Retries exist. A rate limit can be done with a row lock in Postgres. I didn't pick it because the brief asks for Redis atomic operations, and the SIGKILL story maps onto Celery's ack settings more directly than onto "the row stays locked until a timeout".

A custom worker on a Redis list (`BRPOP`, plus a processing list so a crash can be recovered) is less machinery. I'd then own backoff, dead letters, and redelivery myself. That's more code to get wrong for no real gain here.

## Rate limiter

I used a sliding window: a Redis sorted set, `ZREMRANGEBYSCORE` to drop anything older than the window, then `ZADD` if the count is still under the cap.

Fixed window (`INCR` + `EXPIRE`) is shorter, but it has a hole. 200 sends at the end of a minute and 200 at the start of the next minute is 400 in a couple of seconds. The provider's rule is 200 per minute, and that hole is real.

A token bucket (`DECR` + TTL) is smooth and lets you burst up to the bucket size. That's fine for a lot of APIs. I don't want a burst of 200 in one second even if the minute average would have been ok. Some providers punish the spike.

The sliding window never allows more than 200 sends in any 60 second slice. The cost is one sorted-set entry per allowed send, and a Lua script. At 200 a minute the set is tiny.

The whole check is one Lua script in `emailqueue/rate_limit.py`. Redis runs a script by itself, so two workers can't both read "199" and both send. `MULTI`/`EXEC` does not give you that, because another client can get in between the `ZCARD` and the `ZADD` unless you `WATCH` and retry, and a burst turns that into a lot of retries. A pipeline isn't atomic at all. Lua is the one that actually holds.

If the script hits a Redis error, `try_acquire` returns "not allowed". The task does not send. It puts the job back. I'd rather delay mail than blow the provider limit. Fail open is reasonable for a cache. It is a bad default here.

One honest limit of this: the broker is Redis too. If Redis is down, the worker can't pull new jobs anyway. Failing closed doesn't save you from an outage. It stops you from sending unbounded mail while the limiter is the thing that's broken. If Redis is gone for good and there is no AOF or replica, the queued jobs are gone with it. I'm not running a second broker.

## Retries, and why rate-limit waits are not retries

When the limiter says no, I `apply_async` the same payload with a countdown and return. That acks the current message and leaves a new one for later. I do not call `self.retry` for this.

Celery's retry counter would move on every wait. A burst of 2,000 would burn `max_retries` while the jobs were only standing in line, and they'd fall into the dead letter without ever being sent. The failure counter (`emailq:failures:{job_id}`) only moves when the provider returns a transient error.

Backoff for those is `2 ** (failures - 1)` seconds, capped at 60. So 1s, 2s, 4s, 8s, 16s. After 5 provider failures the payload is `LPUSH`ed onto `emailq:dead` and the task returns. A permanent reject (bad address) goes there immediately. Someone can read that list and replay it. I didn't build a replay button. The list is the handling.

## If the worker is SIGKILL'd

Detail is in `ANSWERS.md` under Section 2. Short version: `task_acks_late = True`, `task_reject_on_worker_lost = True`, `worker_prefetch_multiplier = 1`, and `visibility_timeout` of 3600 on the Redis transport. The message stays unacked until the task finishes. A kill puts it back. Delivery is at-least-once, so the task bails out if `emailq:inbox` already has that job id.

There is a small gap. Two workers can both pass that check before either one records the send. A real provider call should also get the job id as an idempotency key. I left that note on `deliver()` rather than pretending the inbox set closes the gap completely.
