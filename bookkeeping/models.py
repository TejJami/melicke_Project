from django.db import models
from django.contrib.postgres.fields import ArrayField  # For account names and IBANs as tags
import psycopg2

# Model to represent tenants within a property
class Tenant(models.Model):
    name = models.CharField(max_length=255)
    other_account_names = models.CharField(max_length=255 , blank=True , null=True)  # Mandatory
    phone_number = models.CharField(max_length=15, blank=True, null=True)  # Optional phone number
    email = models.EmailField(blank=True, null=True)  # Email address
    address = models.TextField(blank=True, null=True)  # Physical address
    iban = models.CharField(max_length=34, blank=True, null=True)  # Bank account IBAN
    bic = models.CharField(max_length=11, blank=True, null=True)  # Optional BIC/SWIFT code
    notes = models.TextField(blank=True, null=True)  # Free text for additional notes

    def __str__(self):
        return f"{self.name}"

# Landlord Model
class Landlord(models.Model):
    name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=15, blank=True, null=True)  # Optional phone number
    email = models.EmailField(blank=True, null=True)  # Email address
    address = models.TextField(blank=True, null=True)  # Physical address
    iban = models.CharField(max_length=34, blank=True, null=True)  # Bank account IBAN
    bic = models.CharField(max_length=11, blank=True, null=True)  # Optional BIC/SWIFT code
    tax_id = models.CharField(max_length=50, blank=True, null=True)  # Tax identification number
    company_name = models.CharField(max_length=255, blank=True, null=True)  # Company name if landlord is a business
    notes = models.TextField(blank=True, null=True)  # Free text for additional notes

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
    date = models.DateField()  # Date of transaction
    account_name = models.CharField(max_length=255, null=True, blank=True)  # Account name
    booking_no = models.CharField(max_length=100, null=True, blank=True)  # Booking number
    transaction_type = models.CharField(max_length=255, null=True, blank=True)  # Transaction type (renamed from gggkto)
    property_name = models.CharField(max_length=255, null=True, blank=True)  # Property name, if applicable
    unit_name = models.CharField(max_length=255, null=True, blank=True)  # Unit name, if applicable
    ust_type = models.IntegerField(choices=[(0, '0%'), (7, '7%'), (19, '19%')], default=19)  # UST type
    betrag_brutto = models.FloatField(null=True, blank=True)  # Gross amount

    def __str__(self):
        return f"{self.date} | {self.account_name} | {self.transaction_type} | {self.betrag_brutto}"

    @property
    def ust(self):
        """Calculate UST dynamically based on the UST type."""
        ust_rate = float(self.ust_type) / 100
        return round(self.betrag_brutto * ust_rate, 2)

    @property
    def betrag_netto(self):
        """Calculate Net Amount dynamically."""
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

    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    ust_type = models.CharField(
        max_length=10,
        choices=[('Nicht', '0'), ('Voll', '19'), ('Teilw', '7')],
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
    TRANSACTION_TYPES = [
        ('bk_back_payments', 'BK Back Payments'),
        ('bk_general_electricity', 'BK General Electricity'),
        ('bk_insurance', 'BK Insurance'),
        ('bk_heating_costs', 'BK Heating Costs'),
        ('other_non_bk', 'Other Non-BK'),
        ('bk_elevator_system', 'BK Elevator System'),
        ('maintenance_direct', 'Maintenance Direct'),
        ('bk_water', 'BK Water'),
        ('bk_drainage', 'BK Drainage'),
        ('bk_caretaker_cleaning', 'BK Caretaker / Cleaning'),
        ('bk_property_taxes', 'BK Property Taxes'),
        ('bk_waste_disposal', 'BK Waste Disposal'),
        ('bk_heating_costs_ista', 'BK Heating Costs per ISTA'),
        ('interest', 'Interest'),
        ('maintenance_activation', 'Maintenance Activation'),
        ('bk_direct', 'BK Direct'),
        ('bk_miscellaneous', 'BK Miscellaneous'),
        ('investment_rent', 'Investment Rent'),
        ('deposit_withdrawal', 'Deposit / Withdrawal'),
    ]

    property = models.ForeignKey(
        Property, related_name='expense_profiles', on_delete=models.CASCADE, null=True, blank=True
    )
    lease = models.ForeignKey(
        Lease, related_name='expense_profiles', on_delete=models.CASCADE, null=True, blank=True
    )
    profile_name = models.CharField(max_length=255)
    transaction_type = models.CharField(
        max_length=50, choices=TRANSACTION_TYPES, default='other_non_bk'
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    date = models.DateField(null=True, blank=True)
    recurring = models.BooleanField(default=False)
    frequency = models.CharField(
        max_length=10, choices=[('monthly', 'Monthly'), ('yearly', 'Yearly')], null=True, blank=True
    )
    account_name = models.CharField(max_length=255)
    ust = models.IntegerField(choices=[(0, '0%'), (7, '7%'), (19, '19%')], default=19)
    booking_no = models.CharField(max_length=100, unique=True)

    def __str__(self):
        if self.lease:
            return f"{self.profile_name} ({self.lease.property.name} - {self.lease.unit.unit_name})"
        elif self.property:
            return f"{self.profile_name} ({self.property.name})"
        return self.profile_name

# Model to represent income categories
class IncomeProfile(models.Model):
    TRANSACTION_TYPES = [
        ('rent', 'Rent'),
        ('bk_advance_payments', 'BK Advance Payments'),
        ('security_deposit', 'Security Deposit'),
        ('subsidy', 'Subsidy'),
        ('deposit_withdrawal', 'Deposit / Withdrawal'),
    ]

    property = models.ForeignKey(
        Property, related_name='income_profiles', on_delete=models.CASCADE, null=True, blank=True
    )
    lease = models.ForeignKey(
        Lease, related_name='income_profiles', on_delete=models.CASCADE, null=True, blank=True
    )
    profile_name = models.CharField(max_length=255)
    transaction_type = models.CharField(
        max_length=30, choices=TRANSACTION_TYPES, default='rent'
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2,null=True, blank=True)
    date = models.DateField(null=True, blank=True)
    recurring = models.BooleanField(default=False)
    frequency = models.CharField(
        max_length=10, choices=[('monthly', 'Monthly'), ('yearly', 'Yearly')], null=True, blank=True
    )
    account_name = models.CharField(max_length=255)
    ust = models.IntegerField(choices=[(0, '0%'), (7, '7%'), (19, '19%')], default=19)
    booking_no = models.CharField(max_length=100, unique=True)

    def __str__(self):
        if self.lease:
            return f"{self.profile_name} ({self.lease.property.name} - {self.lease.unit.unit_name})"
        elif self.property:
            return f"{self.profile_name} ({self.property.name})"
        return self.profile_name
