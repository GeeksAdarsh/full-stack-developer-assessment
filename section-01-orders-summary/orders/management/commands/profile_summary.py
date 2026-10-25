import time
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import connection
from django.db.models import Count
from django.test import Client
from django.test.utils import CaptureQueriesContext

from orders.models import Customer
from orders.services import summary_rows


class Command(BaseCommand):
    help = "Count queries for the broken and fixed summary, and hit silk."

    def handle(self, *args, **options):
        customer = (
            Customer.objects.annotate(n=Count("orders")).order_by("-n").first()
        )
        if customer is None or customer.n == 0:
            self.stderr.write("No orders yet. Run: python manage.py seed_orders")
            return

        broken_queries, broken_ms, broken_rows, broken_sql = self._measure(
            customer.id, fixed=False
        )
        fixed_queries, fixed_ms, fixed_rows, fixed_sql = self._measure(
            customer.id, fixed=True
        )

        from silk.models import Request

        Request.objects.all().delete()

        client = Client()
        client.get(
            "/api/orders/summary/",
            {"customer_id": customer.id, "mode": "broken"},
        )
        client.get("/api/orders/summary/", {"customer_id": customer.id})

        silk_lines = self._silk_lines()

        same = broken_rows == fixed_rows
        text = "\n".join(
            [
                "Orders summary query profile",
                "============================",
                f"Customer: {customer.id} {customer.name}",
                f"Orders: {customer.n}",
                "",
                "These counts are only the summary code (CaptureQueriesContext).",
                "They do not include silk writing its own rows.",
                "",
                f"Broken queryset: {broken_queries} queries in {broken_ms:.1f} ms",
                f"Fixed queryset:  {fixed_queries} queries in {fixed_ms:.1f} ms",
                f"Same response:   {same}",
                "",
                "Broken SQL (first query, trimmed):",
                broken_sql[0],
                "",
                "Fixed SQL (each query, trimmed):",
                "\n".join(fixed_sql),
                "",
                "Silk recorded the same two HTTP calls.",
                "num_sql_queries is silk's count for that request:",
                silk_lines or "  (no silk rows)",
                "",
            ]
        )

        out = Path(__file__).resolve().parents[3] / "evidence" / "query_counts.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        self.stdout.write(text)
        self.stdout.write(f"Wrote {out}")

    def _measure(self, customer_id, *, fixed):
        started = time.perf_counter()
        with CaptureQueriesContext(connection) as ctx:
            rows = summary_rows(customer_id, fixed=fixed)
        elapsed_ms = (time.perf_counter() - started) * 1000
        sql_lines = []
        for i, query in enumerate(ctx.captured_queries, start=1):
            sql = " ".join(query["sql"].split())
            sql_lines.append(f"  [{i}] {sql[:400]}")
        return len(ctx.captured_queries), elapsed_ms, rows, sql_lines

    def _silk_lines(self):
        try:
            from silk.models import Request
        except Exception as exc:
            return f"  silk import failed: {exc}"

        rows = Request.objects.filter(path="/api/orders/summary/").order_by("start_time")
        if not rows:
            return ""
        lines = []
        for row in rows:
            params = row.query_params or ""
            mode = "broken" if "broken" in params else "fixed"
            lines.append(
                f"  {mode}: silk num_sql_queries={row.num_sql_queries}, "
                f"time_taken={row.time_taken} ms, view={row.view_name}"
            )
        return "\n".join(lines)
