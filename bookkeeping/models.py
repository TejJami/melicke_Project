from django.db import models
from django.contrib.postgres.fields import ArrayField  # For account names and IBANs as tags
import psycopg2

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

    def __str__(self):
        return self.name

# Model to represent tenants within a property
class Tenant(models.Model):
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

# Model to represent leases for a property
class Lease(models.Model):
    property = models.ForeignKey(Property, related_name='leases', on_delete=models.CASCADE)
    unit = models.ForeignKey(Unit, related_name='leases', on_delete=models.CASCADE)
    tenant = models.ForeignKey(Tenant, related_name='leases', on_delete=models.CASCADE)
    landlords = models.ManyToManyField(Landlord, related_name='leases')

    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    ust_type = models.CharField(
        max_length=10,
        choices=[('Nicht', 'Nicht'), ('Voll', 'Voll'), ('Teilw', 'Teilw')],
        default='Voll'
    )
    deposit_amount = models.DecimalField(max_digits=10, decimal_places=2)
    rent = models.DecimalField(max_digits=10, decimal_places=2)  # Add rent field
    account_names = ArrayField(models.CharField(max_length=255), blank=True, default=list)
    ibans = ArrayField(models.CharField(max_length=34), blank=True, default=list)

    def __str__(self):
        return f"Lease: {self.property.name} - {self.unit.unit_name} ({self.tenant.name})"


# Model to represent expense categories
class ExpenseProfile(models.Model):
    lease = models.ForeignKey(Lease, related_name='expense_profiles', on_delete=models.CASCADE, null=True, blank=True)
    profile_name = models.CharField(max_length=255)  # Profile name
    transaction_type = models.CharField(
        max_length=50,
        choices=[('repair', 'Repair'), ('maintenance', 'Maintenance'), ('other', 'Other')],
        default='other'
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2,null=True,blank=True)
    date = models.DateField()  # For one-time expenses
    recurring = models.BooleanField(default=False)  # For recurring expenses
    frequency = models.CharField(
        max_length=10,
        choices=[('monthly', 'Monthly'), ('yearly', 'Yearly')],
        null=True,
        blank=True  # Only applicable if recurring=True
    )
    account_name = models.CharField(max_length=255)  # For specifying the account name
    ust = models.IntegerField(choices=[(0, '0%'), (7, '7%'), (19, '19%')], default=19)
    booking_no = models.CharField(max_length=100, unique=True)  # Booking number (BN)

    def __str__(self):
        lease_info = f" - Lease: {self.lease}" if self.lease else " - General"
        return f"{self.profile_name} - {self.transaction_type.capitalize()} - {self.amount}{lease_info}"


# Model to represent income categories
class IncomeProfile(models.Model):
    lease = models.ForeignKey(Lease, related_name='income_profiles', on_delete=models.CASCADE, null=True, blank=True)
    profile_name = models.CharField(max_length=255)  # Profile name
    transaction_type = models.CharField(
        max_length=20,
        choices=[('rent', 'Rent'), ('deposit', 'Deposit')],
        default='rent'
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateField(null=True, blank=True)  # For single events like deposits
    recurring = models.BooleanField(default=False)  # For recurring income like rent
    frequency = models.CharField(
        max_length=10,
        choices=[('monthly', 'Monthly'), ('yearly', 'Yearly')],
        null=True,
        blank=True  # Only applicable if recurring=True
    )
    account_name = models.CharField(max_length=255)  # For specifying the account name
    ust = models.IntegerField(choices=[(0, '0%'), (7, '7%'), (19, '19%')], default=19)  # Tax percentage (linked from lease)
    booking_no = models.CharField(max_length=100, unique=True)  # Booking number (BN)

    def __str__(self):
        lease_info = f" - Lease: {self.lease}" if self.lease else " - General"
        return f"{self.profile_name} - {self.transaction_type.capitalize()} - {self.amount}{lease_info}"
