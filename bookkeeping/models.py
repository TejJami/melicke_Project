from django.db import models

# Model to represent properties
class Property(models.Model):
    name = models.CharField(max_length=255)
    address = models.TextField()

    def __str__(self):
        return self.name

# Model to represent tenants within a property
class Tenant(models.Model):
    property = models.ForeignKey(Property, related_name='tenants', on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    iban = models.CharField(max_length=34)

    def __str__(self):
        return f"{self.name} ({self.property.name})"

# Model to represent expense categories
class ExpenseProfile(models.Model):
    tag = models.CharField(max_length=255)
    iban = models.CharField(max_length=34)

    def __str__(self):
        return self.tag

# Model to represent parsed transactions after categorization
class ParsedTransaction(models.Model):
    date = models.DateField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField()
    is_income = models.BooleanField()
    tenant = models.ForeignKey(Tenant, null=True, blank=True, on_delete=models.SET_NULL)
    expense_profile = models.ForeignKey(ExpenseProfile, null=True, blank=True, on_delete=models.SET_NULL)

    def __str__(self):
        return f"{self.date} | {self.amount} | {'Income' if self.is_income else 'Expense'}"

# Model to represent transactions that are not yet categorized
class EarmarkedTransaction(models.Model):
    date = models.CharField(max_length=10)  # Keep DD.MM.YYYY format as a string
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField()
    is_income = models.BooleanField()

    def __str__(self):
        return f"Earmarked {self.amount} on {self.date}"

