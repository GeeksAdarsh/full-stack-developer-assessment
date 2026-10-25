from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from orders.models import Customer, Order, OrderItem, Product


class Command(BaseCommand):
    help = "Load a big customer (250 orders) and a small one (4 orders)."

    def handle(self, *args, **options):
        with transaction.atomic():
            OrderItem.objects.all().delete()
            Order.objects.all().delete()
            Customer.objects.all().delete()
            Product.objects.all().delete()

            products = [
                Product(
                    sku=f"SKU-{i:03d}",
                    name=f"Item {i}",
                    unit_price=Decimal("99.00") + i,
                )
                for i in range(1, 6)
            ]
            Product.objects.bulk_create(products)
            products = list(Product.objects.order_by("sku"))

            big = Customer.objects.create(
                name="Asha Menon",
                email="asha@example.com",
                city="Pune",
            )
            small = Customer.objects.create(
                name="Rahul Iyer",
                email="rahul@example.com",
                city="Kochi",
            )

            self._load(big, 250, products)
            self._load(small, 4, products)

        self.stdout.write(
            f"Seeded customer {big.id} ({big.name}) with 250 orders, "
            f"and customer {small.id} ({small.name}) with 4 orders."
        )
        self.stdout.write(
            f"Big account: /api/orders/summary/?customer_id={big.id}"
        )

    def _load(self, customer, count, products):
        now = timezone.now()
        statuses = ("paid", "packed", "shipped")
        orders = Order.objects.bulk_create(
            [
                Order(
                    customer=customer,
                    reference=f"{customer.id}-{i:05d}",
                    status=statuses[i % len(statuses)],
                    created_at=now - timedelta(minutes=i),
                )
                for i in range(count)
            ]
        )
        items = []
        for order in orders:
            for n in range(3):
                product = products[(order.id + n) % len(products)]
                items.append(
                    OrderItem(
                        order=order,
                        product=product,
                        quantity=n + 1,
                        unit_price=product.unit_price,
                    )
                )
        OrderItem.objects.bulk_create(items)
