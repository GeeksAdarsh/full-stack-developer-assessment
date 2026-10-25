from django.http import JsonResponse
from django.views.decorators.http import require_GET

from orders.services import summary_rows


@require_GET
def home(request):
    return JsonResponse(
        {
            "summary": "/api/orders/summary/?customer_id=1",
            "broken_for_comparison": "/api/orders/summary/?customer_id=1&mode=broken",
            "profiler": "/silk/",
        }
    )


@require_GET
def order_summary(request):
    # customer_id is a query param so you can open this in a browser.
    # In the real app this would be the logged-in user, not a query string.
    raw = request.GET.get("customer_id", "")
    if not raw.isdigit():
        return JsonResponse({"error": "Pass customer_id as a number."}, status=400)

    fixed = request.GET.get("mode") != "broken"
    rows = summary_rows(int(raw), fixed=fixed)
    return JsonResponse(
        {
            "customer_id": int(raw),
            "mode": "fixed" if fixed else "broken",
            "count": len(rows),
            "orders": rows,
        }
    )
