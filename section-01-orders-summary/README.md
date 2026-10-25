# Orders summary

This is section 1. The mobile dashboard calls `/api/orders/summary/`. After a deploy it started timing out for people with a lot of orders. The view file itself didn't get a new feature. The row it already built started reading the customer, the line items, and the product sku.

The default URL is the fixed version. Add `mode=broken` if you want the old query count in silk.

How to run it is in the root README. Short version, from this folder, with the venv on:

```
python manage.py migrate
python manage.py seed_orders
python manage.py profile_summary
python manage.py test
python manage.py runserver
```

`evidence/query_counts.txt` is the before and after. The write-up is in the root `ANSWERS.md` under Section 1.
