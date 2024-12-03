from django.contrib import admin
from .models import Property,Unit, Tenant, ExpenseProfile, ParsedTransaction, EarmarkedTransaction

admin.site.register(Property)
admin.site.register(Unit)
admin.site.register(Tenant)
admin.site.register(ExpenseProfile)
admin.site.register(ParsedTransaction)
admin.site.register(EarmarkedTransaction)

