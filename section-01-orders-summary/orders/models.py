from decimal import Decimal

from django.db import models


class Customer(models.Model):
    name = models.CharField(max_length=120)
    email = models.EmailField()
    city = models.CharField(max_length=80)

    def __str__(self):
        return self.name


class Product(models.Model):
    sku = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=120)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return self.sku


class Order(models.Model):
    customer = models.ForeignKey(
        Customer, related_name="orders", on_delete=models.CASCADE
    )
    reference = models.CharField(max_length=32, unique=True)
    status = models.CharField(max_length=20)
    created_at = models.DateTimeField()

    class Meta:
        indexes = [
            models.Index(fields=["customer", "created_at"]),
        ]

    def __str__(self):
        # Keep this on columns that live on the order row.
        # Putting customer.name here would add another query per row.
        return self.reference

    def dashboard_row(self):
        """Shape the mobile dashboard asked for.

        The view was already calling this. The slowdown came from the
        fields below, which walk customer, items, and product.
        """
        items = list(self.items.all())
        total = sum((item.line_total for item in items), Decimal("0.00"))
        return {
            "id": self.id,
            "reference": self.reference,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "customer_name": self.customer.name,
            "customer_city": self.customer.city,
            "item_count": len(items),
            "total": f"{total.quantize(Decimal('0.01'))}",
            "skus": [item.product.sku for item in items],
        }


class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name="items", on_delete=models.CASCADE)
    product = models.ForeignKey(
        Product, related_name="order_items", on_delete=models.PROTECT
    )
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

    @property
    def line_total(self):
        return self.unit_price * self.quantity
