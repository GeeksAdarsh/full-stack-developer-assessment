# Full-stack assessment

Three parts, three folders, one repo.

- `section-01-orders-summary` is the orders API that got slow, and the fix.
- `section-02-email-queue` is the email queue that stays under the provider's cap.
- `section-03-architecture-review` is writing only. There is no code in there.

The long notes are in `ANSWERS.md`. The queue design is in `DESIGN.md`. I put those two at the root because the brief asked for them there.

I didn't do the screen recording. That part was optional.

## What you need

Python 3.11 or newer. Redis is only for section 2. Section 1 is sqlite.

## Setup

From this folder:

```
python -m venv .venv
```

Windows:

```
.venv\Scripts\activate
pip install -r requirements.txt
```

Mac or Linux:

```
source .venv/bin/activate
pip install -r requirements.txt
```

## Section 1

```
cd section-01-orders-summary
python manage.py migrate
python manage.py seed_orders
python manage.py profile_summary
python manage.py test
python manage.py runserver
```

Then open http://127.0.0.1:8000/api/orders/summary/?customer_id=1

Customer 1 is Asha, 250 orders, 3 items each. Customer 2 is Rahul, 4 orders. That's why most people still saw a fast page and the heavy accounts timed out.

`profile_summary` writes `evidence/query_counts.txt`. On my machine the old code runs 1251 queries and the fix runs 2. Silk reports the same two numbers.

The old behaviour is still there if you want to see it in silk:

http://127.0.0.1:8000/api/orders/summary/?customer_id=1&mode=broken

Silk itself is at http://127.0.0.1:8000/silk/. No login. I left it open because this is a local demo. Don't ship that.

`customer_id` is a query param so you can hit it from a browser. In the real app that would be the logged-in user.

## Section 2

Start Redis first. From `section-02-email-queue`:

```
docker compose up -d
```

If you don't have Docker, any Redis on `127.0.0.1:6379` is fine.

Then, with the venv still on:

```
cd section-02-email-queue
pytest
```

The 500 job test takes about half a minute. It uses 20 sends per second so it can finish. The real cap is 200 per minute, in `emailqueue/settings.py`. The test checks whatever cap it was started with, and it checks that a failed send gets tried again.

Pytest uses Redis database 1 and clears it. Don't point that at data you care about.

To watch a small run yourself, two terminals, from `section-02-email-queue`:

```
celery -A emailqueue.celery_app worker --pool=solo --loglevel=info
python -m emailqueue.demo
```

On Linux you can leave off `--pool=solo`. On Windows the prefork pool does not work, so solo is the one that runs.

Demo job 3 fails once and then sends. Demo job 4 is a bad address and ends up on the dead-letter list (`emailq:dead` in Redis).

## Section 3

No commands. Read `ANSWERS.md`, the part called Section 3. I answered the slow Django admin question and the pagination question. I left the file upload one.
