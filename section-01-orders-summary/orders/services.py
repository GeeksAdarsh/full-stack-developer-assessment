from django.db.models import Prefetch

from orders.models import Order, OrderItem


def orders_queryset(customer_id, *, fixed):
    """Return one customer's orders, newest first.

    fixed=False is the old queryset. It only filters and sorts.
    dashboard_row() then touches relations, and each touch is a query.

    fixed=True loads the customer with a join, and the items plus their
    products with one extra query. The row builder does not change.
    """
    qs = Order.objects.filter(customer_id=customer_id).order_by("-created_at", "-id")
    if not fixed:
        return qs

    item_qs = OrderItem.objects.select_related("product")
    return qs.select_related("customer").prefetch_related(
        Prefetch("items", queryset=item_qs)
    )


def summary_rows(customer_id, *, fixed):
    return [order.dashboard_row() for order in orders_queryset(customer_id, fixed=fixed)]
