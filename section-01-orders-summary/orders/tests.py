from datetime import timedelta
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from orders.models import Customer, Order, OrderItem, Product
from orders.services import summary_rows

ORDERS = 200
ITEMS_PER_ORDER = 3


def app_queries(ctx):
    # Silk, once the test client has hit it, leaves a cursor wrapper in
    # place. That wrapper adds EXPLAIN QUERY PLAN next to the real SQL.
    kept = []
    for query in ctx.captured_queries:
        sql = query["sql"].lstrip().lower()
        if sql.startswith("explain") or "silk_" in sql:
            continue
        kept.append(query)
    return kept


class OrderSummaryTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(
            name="Asha Menon",
            email="asha@example.com",
            city="Pune",
        )
        self.products = [
            Product.objects.create(
                sku=f"SKU-{i}",
                name=f"Product {i}",
                unit_price=Decimal("10.00") + i,
            )
            for i in range(ITEMS_PER_ORDER)
        ]
        now = timezone.now()
        orders = Order.objects.bulk_create(
            [
                Order(
                    customer=self.customer,
                    reference=f"ORD-{i:05d}",
                    status="paid",
                    created_at=now - timedelta(minutes=i),
                )
                for i in range(ORDERS)
            ]
        )
        OrderItem.objects.bulk_create(
            [
                OrderItem(
                    order=order,
                    product=self.products[n],
                    quantity=n + 1,
                    unit_price=self.products[n].unit_price,
                )
                for order in orders
                for n in range(ITEMS_PER_ORDER)
            ]
        )

    def test_broken_path_runs_a_query_per_relation(self):
        with CaptureQueriesContext(connection) as ctx:
            rows = summary_rows(self.customer.id, fixed=False)

        # 1 for the orders, 1 customer per order, 1 items query per order,
        # 1 product query per item.
        expected = 1 + ORDERS + ORDERS + (ORDERS * ITEMS_PER_ORDER)
        self.assertEqual(len(rows), ORDERS)
        self.assertEqual(len(app_queries(ctx)), expected)

    def test_fixed_path_stays_at_a_couple_of_queries(self):
        with CaptureQueriesContext(connection) as ctx:
            rows = summary_rows(self.customer.id, fixed=True)

        queries = app_queries(ctx)
        self.assertEqual(len(rows), ORDERS)
        # One join for orders+customer, one join for items+product.
        preview = "\n".join(q["sql"][:180] for q in queries)
        self.assertEqual(len(queries), 2, preview)
        sql = " ".join(q["sql"] for q in queries).lower()
        self.assertIn("join", sql)

    def test_both_paths_return_the_same_rows(self):
        broken = summary_rows(self.customer.id, fixed=False)
        fixed = summary_rows(self.customer.id, fixed=True)
        self.assertEqual(broken, fixed)
        self.assertEqual(fixed[0]["customer_name"], "Asha Menon")
        self.assertEqual(fixed[0]["item_count"], ITEMS_PER_ORDER)
        self.assertEqual(len(fixed[0]["skus"]), ITEMS_PER_ORDER)

    def test_endpoint_defaults_to_the_fix(self):
        response = self.client.get(
            "/api/orders/summary/",
            {"customer_id": self.customer.id},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["mode"], "fixed")
        self.assertEqual(body["count"], ORDERS)

        broken = self.client.get(
            "/api/orders/summary/",
            {"customer_id": self.customer.id, "mode": "broken"},
        )
        self.assertEqual(broken.status_code, 200)
        self.assertEqual(broken.json()["orders"], body["orders"])

    def test_missing_customer_id_is_a_client_error(self):
        response = self.client.get("/api/orders/summary/")
        self.assertEqual(response.status_code, 400)
