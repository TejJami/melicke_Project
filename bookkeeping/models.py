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
    PROPERTY_TYPE_CHOICES = [
        ('residential', 'Residential'),
        ('commercial', 'Commercial'),
    ]

    # Property Details
    property_type = models.CharField(max_length=20, choices=PROPERTY_TYPE_CHOICES, default='residential')
    name = models.CharField(max_length=255)
    street = models.CharField(max_length=255)
    building_no = models.CharField(max_length=50)
    city = models.CharField(max_length=100)
    zip = models.CharField(max_length=10)
    country = models.CharField(max_length=100)
    landlords = models.ManyToManyField(Landlord, related_name='owned_properties')  # Multiple landlords can own a property
    potential_rent = models.FloatField(default=0.0)

    def __str__(self):
        return self.name

# Model to represent tenants within a property
class Tenant(models.Model):
    property = models.ForeignKey(Property, related_name='tenants', on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    iban = models.CharField(max_length=34)

    def __str__(self):
        return f"{self.name} ({self.property.name})"

# Unit Model (Part of the Property)
class Unit(models.Model):
    property = models.ForeignKey(Property, related_name='units', on_delete=models.CASCADE)  # Links unit to a property
    unit_name = models.CharField(max_length=255)  # E.g., "Unit A", "Flat 1B"
    floor_area = models.FloatField(help_text="Floor area in square meters")  # Floor area in sq.m.
    rooms = models.IntegerField(help_text="Number of rooms in the unit")  # Number of rooms
    baths = models.IntegerField(help_text="Number of bathrooms in the unit")  # Number of bathrooms
    market_rent = models.DecimalField(max_digits=10, decimal_places=2, help_text="Market rent for the unit")  # Rent in currency

    def __str__(self):
        return f"{self.unit_name} - {self.property.name}"


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

