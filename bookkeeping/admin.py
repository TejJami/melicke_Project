from django.contrib import admin
from .models import Property,Unit, Tenant, ExpenseProfile, ParsedTransaction, EarmarkedTransaction , IncomeProfile , Lease  , Landlord 

admin.site.register(Property)
admin.site.register(Unit)
admin.site.register(Tenant)
admin.site.register(ExpenseProfile)
admin.site.register(IncomeProfile)
admin.site.register(ParsedTransaction)
admin.site.register(EarmarkedTransaction)
admin.site.register(Lease)
admin.site.register(Landlord)


