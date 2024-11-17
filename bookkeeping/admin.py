from django.contrib import admin
from .models import Property, Tenant, ExpenseProfile, ParsedTransaction, EarmarkedTransaction

admin.site.register(Property)
admin.site.register(Tenant)
admin.site.register(ExpenseProfile)
admin.site.register(ParsedTransaction)
admin.site.register(EarmarkedTransaction)
