from django.db import models

# Landlord Model
class Landlord(models.Model):
    name = models.CharField(max_length=255)
    contact_info = models.TextField()  # Could be an email, phone, or address
    iban = models.CharField(max_length=34, blank=True, null=True)  # Optional IBAN for payments

    def __str__(self):
        return self.name

# Property Model (Building)
class Property(models.Model):
    name = models.CharField(max_length=255)  # Property name
    address = models.TextField()  # Full address
    landlord = models.ForeignKey(Landlord, related_name='properties' , null=True, blank=True,on_delete=models.SET_NULL)     # Link to the landlord
    potential_rent = models.FloatField(default=0.0)  # Total potential rent
    actual_rent = models.FloatField(default=0.0)  # Automatically calculated from unit rents
    def __str__(self):
        return self.name

    def calculate_actual_rent(self):
        """Calculate actual rent from the units that are leased (filled)."""
        self.actual_rent = sum(unit.rent for unit in self.units.filter(lease_status='filled'))
        self.save()
        return self.actual_rent

# Model to represent tenants within a property
class Tenant(models.Model):
    property = models.ForeignKey(Property, related_name='tenants', on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    iban = models.CharField(max_length=34)

    def __str__(self):
        return f"{self.name} ({self.property.name})"

# Unit Model (Part of the Property)
class Unit(models.Model):
    LEASE_STATUS_CHOICES = [
        ('empty', 'Empty'),
        ('renovation', 'Under Renovation'),
        ('filled', 'Leased'),
    ]

    property = models.ForeignKey(Property, related_name='units', on_delete=models.CASCADE)
    unit_name = models.CharField(max_length=255)  # E.g., "Unit A", "Flat 1B"
    lease_status = models.CharField(max_length=15, choices=LEASE_STATUS_CHOICES, default='empty')
    rent = models.FloatField(default=0.0)  # Rent for this unit
    maintenance = models.FloatField(default=0.0)  # Maintenance cost

    def __str__(self):
        return f"{self.unit_name} - {self.property.name}"

    def save(self, *args, **kwargs):
        """Update property's actual rent when unit details change."""
        super().save(*args, **kwargs)
        self.property.calculate_actual_rent()


# Model to represent expense categories
class ExpenseProfile(models.Model):
    UST_CHOICES = [(0, '0%'), (7, '7%'), (19, '19%')]
    UST_SCH_CHOICES = [('Nicht', 'Nicht'), ('Voll', 'Voll'), ('Teilw', 'Teilw')]

    profile_name = models.CharField(max_length=255, unique=True)
    account_name = models.CharField(max_length=255, unique=True)
    ust = models.IntegerField(choices=UST_CHOICES, default=19)
    ust_sch = models.CharField(max_length=10, choices=UST_SCH_CHOICES, default='Voll')
    transactions = models.ManyToManyField('ParsedTransaction', related_name='expense_profiles', blank=True)

    # Updated related names
    property = models.ForeignKey(
        Property,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='property_expense_profiles',  # Unique name for the reverse relation
    )
    unit = models.ForeignKey(
        Unit,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='unit_expense_profiles',  # Unique name for the reverse relation
    )

    def __str__(self):
        return f"{self.profile_name} ({self.account_name})"


# Model to represent parsed transactions after categorization
class ParsedTransaction(models.Model):
    date = models.DateField()
    account_name = models.CharField(max_length=255, null=True, blank=True)  # New field for account name
    #on deletetion of the linked ExpenseProfile delete the ParsedTransaction
    gggkto = models.ForeignKey('ExpenseProfile', null=True, blank=True, on_delete=models.CASCADE)
    betrag_brutto = models.FloatField(null=True, blank=True)  # Original amount

    def __str__(self):
        return f"{self.date} | {self.account_name} | {self.betrag_brutto} | {self.gggkto}"

    @property
    def ust(self):
        """Calculate UST dynamically based on the linked ExpenseProfile."""
        if self.gggkto:
            ust_rate = float(self.gggkto.ust) / 100
            return round(self.betrag_brutto * ust_rate, 2)
        return 0.0

    @property
    def betrag_netto(self):
        """Calculate Betrag Netto dynamically based on the linked ExpenseProfile."""
        return round(self.betrag_brutto - self.ust, 2)


# Model to represent transactions that are not yet categorized
class EarmarkedTransaction(models.Model):
    date = models.CharField(max_length=10)  # Keep DD.MM.YYYY format as a string
    amount = models.FloatField()    
    description = models.TextField()
    is_income = models.BooleanField()
    account_name = models.CharField(max_length=255, null=True, blank=True)  # New field for account name

    def __str__(self):
        return f"Earmarked {self.amount} on {self.date}"

