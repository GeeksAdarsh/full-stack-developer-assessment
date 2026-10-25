# Email queue

This is section 2. Transactional mail (order confirmations, OTP, alerts) has to stay under 200 sends in any 60 second window, survive a worker crash, and retry when the provider blips.

The code is Celery with Redis. The rate limiter is a small Lua script in `emailqueue/rate_limit.py`, not a library. Why that shape, and what I turned down, is in the root `DESIGN.md`. The SIGKILL write-up is in `ANSWERS.md` under Section 2.

## Run

Redis has to be up.

```
docker compose up -d
pytest
```

Worker and a small demo, two terminals:

```
celery -A emailqueue.celery_app worker --pool=solo --loglevel=info
python -m emailqueue.demo
```

Windows needs `--pool=solo`. Linux can use the normal pool.

Production numbers are 200 emails and a 60 second window. `pytest` lowers that to 20 per second so 500 jobs don't take several minutes. Same limiter either way.
