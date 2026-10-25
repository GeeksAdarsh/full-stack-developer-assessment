"""Queue tests.

Production cap is 200 emails in any 60 second window. See emailqueue/settings.py.
conftest.py lowers that to 20 per second so this file can finish locally.
The limiter is the same code. Assertions use the limit from settings,
not a hard-coded 200.
"""

import collections
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import redis
from redis.exceptions import RedisError

from emailqueue.celery_app import app
from emailqueue.rate_limit import SlidingWindowLimiter
from emailqueue.settings import QUEUE_NAME, RATE_LIMIT, RATE_WINDOW_MS, REDIS_URL
from emailqueue.tasks import DEAD, INBOX, REQUEUES, send_transactional_email

ROOT = Path(__file__).resolve().parents[1]
JOBS = 500


def client_or_fail():
    client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        client.ping()
    except redis.exceptions.ConnectionError:
        pytest.fail(
            "Redis is not running on 127.0.0.1:6379.\n"
            "From section-02-email-queue: docker compose up -d"
        )
    return client


def window_ok(scores_ms, limit, window_ms):
    """True when every window holds at most `limit` events.

    Matches the Lua script: a score is still inside the window when
    now - score < window_ms. A score exactly window_ms older is dropped.
    """
    times = sorted(scores_ms)
    left = 0
    busiest = 0
    for right, stamp in enumerate(times):
        while stamp - times[left] >= window_ms:
            left += 1
        busiest = max(busiest, right - left + 1)
        if busiest > limit:
            return False, busiest
    return True, busiest


def test_worker_survives_sigkill_settings():
    # The written answer in ANSWERS.md hangs off these exact flags.
    assert send_transactional_email.acks_late is True
    assert send_transactional_email.reject_on_worker_lost is True
    assert app.conf.task_acks_late is True
    assert app.conf.task_reject_on_worker_lost is True
    assert app.conf.worker_prefetch_multiplier == 1
    assert app.conf.broker_transport_options["visibility_timeout"] == 3600


def test_sliding_window_rejects_the_burst_over_the_cap():
    client = client_or_fail()
    for key in client.scan_iter("clock:*"):
        client.delete(key)

    limiter = SlidingWindowLimiter(client, limit=10, window_ms=1000, prefix="clock")
    now = 1_700_000_000_000
    first = [
        limiter.try_acquire(f"a-{i}", now_ms=now)[0]
        for i in range(50)
    ]
    assert sum(first) == 10

    # Exactly one window later the old scores are out, so 10 more fit.
    second = [
        limiter.try_acquire(f"b-{i}", now_ms=now + 1000)[0]
        for i in range(20)
    ]
    assert sum(second) == 10
    assert client.zcard("clock:accepted") == 20


def test_parallel_callers_cannot_break_the_cap():
    client = client_or_fail()
    for key in client.scan_iter("burst:*"):
        client.delete(key)

    limit = 8
    limiter = SlidingWindowLimiter(client, limit=limit, window_ms=30_000, prefix="burst")
    results = []
    lock = threading.Lock()

    def hit(i):
        allowed, _wait = limiter.try_acquire(f"t-{i}-{time.time_ns()}")
        with lock:
            results.append(allowed)

    threads = [threading.Thread(target=hit, args=(i,)) for i in range(40)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sum(results) == limit


def test_redis_error_fails_closed(monkeypatch):
    client = client_or_fail()
    limiter = SlidingWindowLimiter(client, limit=5, window_ms=1000, prefix="closed")

    def boom(*args, **kwargs):
        raise RedisError("connection refused")

    monkeypatch.setattr(limiter, "_script", boom)
    allowed, wait = limiter.try_acquire("nobody")
    assert allowed is False
    assert wait == 1.0


def test_rate_limit_requeues_instead_of_sending(monkeypatch):
    client = client_or_fail()
    client.flushdb()

    monkeypatch.setattr(
        "emailqueue.tasks.limiter.try_acquire",
        lambda member, now_ms=None: (False, 1.0),
    )
    result = send_transactional_email.run(
        {"job_id": "held-1", "kind": "otp", "to": "a@example.com"}
    )
    assert result == "rate_limited"
    assert client.scard(INBOX) == 0
    assert int(client.get(REQUEUES)) == 1
    # The job is sitting on the broker, not dropped.
    queued = sum(client.llen(key) for key in client.scan_iter(f"{QUEUE_NAME}*"))
    assert queued >= 1


def test_500_jobs_are_kept_under_the_limit_and_retried():
    client = client_or_fail()
    client.flushdb()

    log = collections.deque(maxlen=200)
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "celery",
            "-A",
            "emailqueue.celery_app",
            "worker",
            "--pool=solo",
            "--concurrency=1",
            "--loglevel=info",
            "-Q",
            QUEUE_NAME,
            "--without-gossip",
            "--without-mingle",
            "--without-heartbeat",
        ],
        cwd=str(ROOT),
        env=os.environ.copy(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    def drain():
        for line in proc.stdout:
            log.append(line.rstrip())

    threading.Thread(target=drain, daemon=True).start()

    try:
        _wait_until_ready(proc, log)
        for i in range(JOBS):
            job = {
                "job_id": f"job-{i}",
                "kind": "order_confirmation",
                "to": f"user{i}@example.com",
            }
            if i == 7:
                job["fail_times"] = 1
            if i == 11:
                job["permanent"] = True
            send_transactional_email.delay(job)

        deadline = time.time() + 120
        while time.time() < deadline:
            done = client.scard(INBOX) + client.llen(DEAD)
            if done >= JOBS:
                break
            if proc.poll() is not None:
                pytest.fail("worker died\n" + "\n".join(log))
            time.sleep(0.4)
        else:
            pytest.fail(
                "timed out waiting for 500 jobs\n"
                f"inbox={client.scard(INBOX)} dead={client.llen(DEAD)} "
                f"requeues={client.get(REQUEUES)}\n" + "\n".join(log)
            )

        inbox = client.smembers(INBOX)
        dead_ids = [
            json.loads(raw)["job"]["job_id"] for raw in client.lrange(DEAD, 0, -1)
        ]
        expected = {f"job-{i}" for i in range(JOBS)}
        assert set(dead_ids) == {"job-11"}
        assert inbox.isdisjoint(dead_ids)
        assert inbox | set(dead_ids) == expected

        # Job 7 was rejected once by the provider, then sent.
        assert int(client.get("emailq:runs:job-7")) >= 2
        assert "job-7" in inbox
        assert int(client.get("emailq:fail_seen:job-7")) == 1

        requeues = int(client.get(REQUEUES) or 0)
        assert requeues > 0, "rate limit never pushed back a job"

        scores = [score for _member, score in client.zrange("emailq:accepted", 0, -1, withscores=True)]
        ok, busiest = window_ok(scores, RATE_LIMIT, RATE_WINDOW_MS)
        assert ok, f"busiest window had {busiest}, limit is {RATE_LIMIT}"
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


def _wait_until_ready(proc, log):
    deadline = time.time() + 40
    while time.time() < deadline:
        if proc.poll() is not None:
            pytest.fail("worker exited before it was ready\n" + "\n".join(log))
        if any("ready" in line.lower() for line in log):
            return
        time.sleep(0.2)
    pytest.fail("worker never printed ready\n" + "\n".join(log))
