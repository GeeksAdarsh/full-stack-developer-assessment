from django.contrib import admin
from django.urls import include, path

from orders.views import home, order_summary

urlpatterns = [
    path("", home),
    path("admin/", admin.site.urls),
    path("api/orders/summary/", order_summary, name="order-summary"),
    path("silk/", include("silk.urls", namespace="silk")),
]
