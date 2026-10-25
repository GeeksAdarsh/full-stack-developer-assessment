# Answers

## Section 1. Orders summary timeout

### What I checked, in order

The brief says the view didn't change in the deploy, and only accounts with a lot of orders got slow. I treated that as the clue.

1. Is the whole site sick, or one shape of data? A customer with a handful of orders stays fast. A customer with 250 orders is the one that hurts. So this is not a dead database or a deploy that broke every request. It depends on how many rows that user has.

2. What actually changed, if the view file didn't? The view still loads that customer's orders and builds a row for each one. The row is `Order.dashboard_row()`. The dashboard started asking for the customer name, the item count, the money total, and the product skus. That work landed inside the row builder the view was already calling. The view diff can be empty and the page still gets slower. I kept `?mode=broken` so the old queryset is still callable.

3. A missing index? It doesn't explain a timeout that grows with the number of orders like this. `customer_id` is a foreign key, so Django already indexes it. Each extra query is a primary key lookup. Those are cheap one at a time. I did add an index on `(customer, created_at)` because the list is ordered by `created_at`. That only helps the first query. It does nothing about the thousand after it.

4. A cache problem? Nothing here was cached before. There's no stale key and no stampede to chase.

5. The query log. I counted with `CaptureQueriesContext`, and I sent both URLs through django-silk. For Asha (250 orders, 3 items each) the old path runs 1 query for the orders, then 1 per order for the customer, 1 per order for the items, and 1 per item for the product. That's 1 + 250 + 250 + 750 = 1251 queries. Silk's `num_sql_queries` for that request is 1251. The fixed path is 2 queries, and silk says 2 as well. The numbers are in `section-01-orders-summary/evidence/query_counts.txt`.

On this laptop, sqlite answers those tiny queries locally, so 1251 of them is under a second in the query counter and about 2.2 seconds once silk is recording the HTTP call. The production symptom is 30 seconds because each of those queries is a round trip to another machine. The thing that changed between the two versions is the number of round trips, from 1251 to 2.

I also checked `Order.__str__`. A `__str__` that touches a foreign key causes the same kind of blow-up in the admin and anywhere else a row gets printed. This one returns `reference`, which is a column on the order.

### Root cause

N+1 queries. More precisely: N+1 on `customer`, N+1 on `items`, and then one query per item for `product`.

That's normal ORM behaviour. Reading `order.customer` when the queryset was not `select_related` issues a new `SELECT`. Reading `order.items` when it was not prefetched issues a new `SELECT`. Reading `item.product` does it again. It was cheap when the row only used columns on `orders_order`. It stopped being cheap when the row started walking relations, and the queryset in the view was never told.

### Why the fix works

`select_related("customer")` adds a SQL `JOIN` to the first query. The customer columns come back on the same row. Django fills `order.customer` from those columns, so touching `.name` or `.city` does not hit the database.

`prefetch_related` with a `Prefetch` on `"items"` runs one more query: `WHERE order_id IN (...)`. Django then attaches those items to the right orders in Python. The prefetch queryset uses `select_related("product")`, so that second query joins `product` too. `item.product.sku` reads the joined row.

After that, the loop in the view is just reading objects that are already in memory. The JSON is the same as the old path. The tests check that, and they check the query counts (1001 on the old path for 200 orders, 2 on the new one).

I didn't switch this to `values()` or `only()`. The response needs the nested items and the skus, and a join plus a prefetch stays readable. `annotate(Count(...), Sum(...))` would be enough if we only needed totals. The sku list needs the item rows anyway.

## Section 2. What happens if the worker is SIGKILL'd

By default Celery acks a message when the worker receives it, then starts the work. If you SIGKILL the process after that ack, the broker has already forgotten the job. It's gone.

I turned that off. `task_acks_late = True` on the app, and `acks_late=True` on `send_transactional_email`. The ack is sent after the function returns. I also set `task_reject_on_worker_lost = True` (and `reject_on_worker_lost=True` on the task). Celery's own docs call out KILL here: if the worker process disappears, the task is rejected instead of acked, so the broker can deliver it again.

With the Redis broker the in-flight message sits in the unacked set. `broker_transport_options["visibility_timeout"]` is 3600 seconds. If the kill happens before the worker's reject gets out (SIGKILL doesn't run your `finally`), Redis still puts the message back when that timeout expires. The job is not deleted on pickup.

`worker_prefetch_multiplier = 1` so a worker doesn't reserve a pile of messages it hasn't started. A kill then returns the one job it was actually running, not a pocketful of others.

This is at-least-once. A job can run twice if the process dies after the provider accepted the mail and before the ack. The task checks `emailq:inbox` for the job id at the start and skips the send if it's already there. There's still a gap: two workers can both pass that check before either one records the send. Closing that properly means the provider also treats `job_id` as an idempotency key. `deliver()` is where that would be passed. I didn't pretend the Redis set covers that race by itself.

Rate-limit waits are not Celery retries. If they were, a sale of 2,000 emails would use up `max_retries` just waiting for a free slot, and the mail would hit the dead letter without being sent. When the limiter says no, the task does `apply_async` with a countdown and returns normally. The failure counter only moves on a real provider error. Backoff is `2 ** (failures - 1)` seconds, capped at 60. After 5 of those, or on a permanent reject, the payload is pushed onto `emailq:dead`.

If Redis errors during the rate-limit check, the limiter returns "not allowed" and the task requeues. It does not send. That's fail closed. The trade-off is mail waits while Redis is unhappy, which is the same moment the broker is unhappy too.

## Section 3

I answered A and B. I left C.

### Question A. Django admin on a big table

The primary key index is a red herring. Admin already looks rows up by primary key. I would check three other things.

First, foreign keys on the changelist. If `list_display` includes a ForeignKey, Django loads that related object with its own query for every row on the page. A hundred rows and two relations is a couple of hundred round trips, and the page feels stuck even though each query is tiny. I would set `list_select_related` on the ModelAdmin to the relations the list actually shows, for example `list_select_related = ("customer",)`. That turns the changelist into one query with a SQL join. If the slow screen is the edit form rather than the list, the form's ModelChoiceField loads every related row into a select box. I would set `autocomplete_fields = ("customer",)` so Django uses the autocomplete endpoint and fetches a page of matches instead of the whole table.

Second, the full count. The admin paginator runs `COUNT(*)` to print the total number of results. On 500,000 rows that count runs on every load, and it gets worse when a `list_filter` is on and those columns are not indexed. I would set `show_full_result_count = False`. The page still paginates. It just stops computing the exact total.

Third, search and `date_hierarchy`. A `search_fields` entry that uses `icontains` becomes `LIKE '%term%'`. The leading wildcard means a normal btree index cannot help, so the database scans the table. `date_hierarchy` adds extra queries to build the year and month drill-down. I would remove `date_hierarchy` if it is only there by default, add a composite index that matches the filter people actually use and the ordering the changelist uses (`status`, `created_at` is the usual pair), and point `search_fields` at a column that can use an index. I would confirm each change with django-silk or the debug toolbar against a copy of the large table. A laptop database with a few hundred rows will hide all three of these.

### Question B. Offset pagination vs cursor pagination

Offset pagination is the normal Django approach. `Paginator`, and on an API DRF's `PageNumberPagination`, turn "page 50" into `LIMIT 20 OFFSET 980`. The database still has to walk those 980 rows and throw them away. Early pages are fine. Someone scrolling a long way pays more on every page, which is a bad match for a mobile infinite list.

It also moves while you read it. If the list is newest first and a row is inserted at the top during the scroll, every later offset shifts by one. The app repeats a row or skips one. A delete does the same thing the other way. I would keep offset where the list is short, the rows are not changing under the user, and someone needs to jump to a page or share a link like `?page=12`. Admin screens are the usual case.

Cursor pagination does not send a page number. DRF's `CursorPagination`, and Django's `CursorPaginator` in `django.core.paginator`, send the last row the client already has. The next query is a range on a stable order: `WHERE (created_at, id) < (last_created_at, last_id) ORDER BY created_at DESC, id DESC LIMIT 20`. The database seeks into the index, so a deep page costs about the same as the first page. A new row above the cursor does not shift the next page, so infinite scroll stops repeating items. `created_at` alone is not safe if two rows can share a timestamp, which is why the cursor has to include the primary key.

You give up random access. There is no honest "go to page 40", and printing "page 7 of 400" needs a separate `COUNT(*)` that brings the expensive count back. I would use a cursor for the mobile order feed and leave offset in place for small, calm lists where jumping to a page matters more than scrolling deep.
