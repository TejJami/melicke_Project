from django.db import models
from django.contrib.postgres.fields import ArrayField  # For account names and IBANs as tags
import psycopg2
from django.contrib.auth.models import User
from django.db import models
from decimal import Decimal
from django.core.cache import cache
from django.db import models


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
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00) 

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
    object = models.CharField(max_length=255, blank=True, null=True)  # New field for object reference
    notes = models.TextField(blank=True, null=True)  # Free text for additional notes

    def __str__(self):
        return f"{self.name} - {self.object if self.object else 'No Object'}"

# Model to represent properties
class Property(models.Model):
    PROPERTY_TYPE_CHOICES = [
        ('Residential', 'Residential'),
        ('Commercial', 'Commercial'),
        ('Mixed Use', 'Mixed Use'),
    ]

    TAX_CALCULATION_CHOICES = [
        ('none', 'Manually Entered'),
        ('sq_meterage', 'Based on Sq Meterage'),
        ('income', 'Based on Income'),
    ]

    property_type = models.CharField(max_length=20, choices=PROPERTY_TYPE_CHOICES, default='Residential')
    name = models.CharField(max_length=255)
    street = models.CharField(max_length=255)
    building_no = models.CharField(max_length=50)
    city = models.CharField(max_length=100)
    zip = models.CharField(max_length=10)
    country = models.CharField(max_length=100)
    landlords = models.ManyToManyField('Landlord', related_name='owned_properties')  
    image = models.ImageField(upload_to='property_images/', null=True, blank=True)

    # Updated to DecimalField to always store two decimal places
    partial_tax_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, default=Decimal("0.00"))

    # New fields for automatic calculation with null=True
    auto_calculate_tax = models.BooleanField(default=False, null=True, blank=True)
    tax_calculation_method = models.CharField(
        max_length=15, choices=TAX_CALCULATION_CHOICES, default='none', null=True, blank=True
    )

    locked_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='locked_properties')

    @staticmethod
    def get_next_default_image():
        default_images = [
            'property_images/default1.png',
            'property_images/default2.jpg',
            'property_images/default3.jpg',
            'property_images/default4.jpg',
            'property_images/default5.jpg',
            'property_images/default6.jpg',
        ]
        count = Property.objects.count()
        index = count % len(default_images)
        return default_images[index]


    def save(self, *args, **kwargs):
        if not self.image:
            self.image = self.get_next_default_image()
        
        # Ensure partial tax rate always has two decimal places
        if self.partial_tax_rate is not None:
            self.partial_tax_rate = Decimal(self.partial_tax_rate).quantize(Decimal("0.00"))

        super().save(*args, **kwargs)

# Model to represent units within a property
class Unit(models.Model):

    property = models.ForeignKey(Property, related_name='units', on_delete=models.CASCADE)  # Links unit to a property
    unit_name = models.CharField(max_length=255)  # E.g., "Unit A", "Flat 1B"
    floor = models.IntegerField(help_text="Floor number of the unit", null=True, blank=True)  # Floor level
    floor_area = models.FloatField(help_text="Floor area in square meters", null=True, blank=True,)  # Floor area in sq.m.
    rent = models.DecimalField(max_digits=10, decimal_places=2, help_text="Rent for the unit", null=True, blank=True,)  # Renamed from market_rent
    additional_costs = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Additional costs")  # New field for extra costs
    stellplatz_miete = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Parking space rent")  # New field for parking space rent
    investition_miete = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Investment rent")  # New field for investment rent    

    def __str__(self):
        return f"{self.unit_name} - {self.property.name})"
     
# Model to represent parsed transactions after categorization
class ParsedTransaction(models.Model):
    date = models.DateField()  # Date of transaction
    account_name = models.CharField(max_length=255, null=True, blank=True)  # Account name
    booking_no = models.CharField(max_length=100, null=True, blank=True)  # Booking number
    transaction_type = models.CharField(max_length=255, null=True, blank=True)  # Transaction type (renamed from gggkto)
    # property_name = models.CharField(max_length=255, null=True, blank=True)  # Property name, if applicable
    related_property = models.ForeignKey(Property, on_delete=models.CASCADE, null=True, blank=True)  # Link to property
    unit_name = models.CharField(max_length=255, null=True, blank=True)  # Unit name, if applicable
    ust_type = models.IntegerField(choices=[(0, '0%'), (7, '7%'), (19, '19%')], default=19)  # UST type
    betrag_brutto = models.FloatField(null=True, blank=True)  # Gross amount
    is_income = models.BooleanField()
    tenant = models.CharField(max_length=255, null=True, blank=True)  # Tenant name
    invoice = models.URLField(null=True, blank=True) 
    
    def __str__(self):
        return f"{self.date} | {self.account_name} | {self.transaction_type} | {self.betrag_brutto}"

    def save(self, *args, **kwargs):
        if not self.invoice:
            try:
                matched = ExpenseProfile.objects.filter(
                    account_name=self.account_name,
                    amount=self.betrag_brutto,
                    property=self.related_property
                ).first()
                if matched and matched.invoice:
                    self.invoice = matched.invoice
            except Exception as e:
                logging.error(f"[ParsedTransaction.save] Failed to match invoice: {e}")
        super().save(*args, **kwargs)

    @property
    def ust(self):
        try:
            return round(self.betrag_brutto - (self.betrag_brutto / (1 + self.ust_type / 100)), 2)
        except (TypeError, ZeroDivisionError):
            return 0

    @property
    def betrag_netto(self):
        try:
            return round(self.betrag_brutto / (1 + self.ust_type / 100), 2)
        except (TypeError, ZeroDivisionError):
            return 0


# Model to represent transactions that are not yet categorized
class EarmarkedTransaction(models.Model):
    
    property = models.ForeignKey(Property, on_delete=models.CASCADE, null=True, blank=True)  # Associate with a property
    date = models.CharField(max_length=10)  # Keep DD.MM.YYYY format as a string
    amount = models.FloatField()    
    description = models.TextField()
    is_income = models.BooleanField()
    account_name = models.CharField(max_length=255, null=True, blank=True)  # New field for account name
    booking_no = models.CharField(max_length=20, blank=True, null=True)  # Add this field
    flagged_for_review = models.BooleanField(default=False)
    review_note = models.TextField(blank=True, null=True)
    resolved = models.BooleanField(default=False)

    def __str__(self):
        return f"Earmarked {self.amount} on {self.date}"

# Model to represent leases for a property
class Lease(models.Model):
    property = models.ForeignKey(Property, related_name='leases', on_delete=models.CASCADE)
    unit = models.ForeignKey(Unit, related_name='leases', on_delete=models.CASCADE)
    tenants = models.ManyToManyField(Tenant, related_name='leases')

    landlords = models.ManyToManyField(Landlord, related_name='leases')

    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    ust_type = models.CharField(
        max_length=10,
        choices=[('Ohne', '0'), ('Mit', '19')],
        default='Ohne'
    )
    deposit_amount = models.DecimalField(max_digits=10, decimal_places=2)
    guarantee = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    rent = models.DecimalField(max_digits=10, decimal_places=2)  # Add rent field
    additional_costs = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Additional costs for the lease")

    account_names = ArrayField(models.CharField(max_length=255), blank=True, default=list)
    ibans = ArrayField(models.CharField(max_length=34), blank=True, default=list)

    def __str__(self):
        return f"Lease: {self.property.name} - {self.unit.unit_name} - {self.tenants.first().name if self.tenants.exists() else 'No Tenant'}"

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
    # profile_name = models.CharField(max_length=255)
    transaction_type = models.CharField(
        max_length=50, choices=TRANSACTION_TYPES, default='other_non_bk'
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    date = models.DateField(null=True, blank=True)
    recurring = models.BooleanField(default=False)
    frequency = models.CharField(
        max_length=12,
        choices=[
            ('monthly', 'Monatlich'),
            ('bimonthly', 'Zweimonatlich'),
            ('quarterly', 'Vierteljährlich'),
            ('yearly', 'Jährlich')
        ],
        null=True,
        blank=True
    )
    account_name = models.CharField(max_length=255)
    ust = models.IntegerField(choices=[(0, '0%'), (7, '7%'), (19, '19%')], default=19)
    invoice = models.URLField(blank=True, null=True) 

    def __str__(self):
        if self.lease:
            return f"({self.lease.property.name} - {self.lease.unit.unit_name})"
        elif self.property:
            return f"({self.property.name})"
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
    # lease = models.ForeignKey(
    #     Lease, related_name='income_profiles', on_delete=models.CASCADE, null=True, blank=True
    # )
    leases = models.ManyToManyField(Lease, related_name='income_profiles', blank=True)
    # profile_name = models.CharField(max_length=255)
    transaction_type = models.CharField(
        max_length=30, choices=TRANSACTION_TYPES, default='rent' , null=True, blank=True
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2,null=True, blank=True)
    date = models.DateField(null=True, blank=True)
    recurring = models.BooleanField(default=False)
    frequency = models.CharField(
        max_length=12,
        choices=[
            ('monthly', 'Monatlich'),
            ('bimonthly', 'Zweimonatlich'),
            ('quarterly', 'Vierteljährlich'),
            ('yearly', 'Jährlich')
        ],
        null=True,
        blank=True
    )
    account_name = models.CharField(max_length=255)
    ust = models.IntegerField(choices=[(0, '0%'), (7, '7%'), (19, '19%')], default=19)
    # booking_no = models.CharField(max_length=100, unique=False)
    split_details = models.JSONField(
        null=True,
        blank=True,
        help_text="Optional: define exact split for this profile, e.g. {'rent': 1500, 'bk_advance_payments': 250, 'security_deposit': 250}"
    )
    def __str__(self):
        if self.property:
            return f"({self.property.name} - {self.account_name})"
        return self.profile_name if hasattr(self, 'profile_name') else "Income Profile"
