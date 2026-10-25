from django.contrib import admin

from orders.models import Customer, Order, OrderItem, Product

admin.site.register(Customer)
admin.site.register(Product)
admin.site.register(Order)
admin.site.register(OrderItem)
