import time


class TransientEmailError(Exception):
    """Provider had a blip. Safe to try again."""


class PermanentEmailError(Exception):
    """Provider will reject this again. Don't keep retrying."""


def deliver(client, job):
    """Stand-in for the email provider.

    fail_times: the first N calls raise a 503, then it accepts.
    permanent: a bad address. It never succeeds.

    A real sender would also pass job_id to the provider as an
    idempotency key, so a replay after a crash does not double-send.
    """
    job_id = str(job["job_id"])
    if job.get("permanent"):
        raise PermanentEmailError("provider rejected the address")

    fail_times = int(job.get("fail_times") or 0)
    seen_key = f"emailq:fail_seen:{job_id}"
    seen = int(client.get(seen_key) or 0)
    if seen < fail_times:
        client.incr(seen_key)
        raise TransientEmailError("provider returned 503")

    client.sadd("emailq:inbox", job_id)
    member = f"{job_id}:{time.time_ns()}"
    client.zadd("emailq:delivered", {member: int(time.time() * 1000)})
