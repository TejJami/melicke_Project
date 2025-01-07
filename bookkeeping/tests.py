from django.test import TestCase
from .models import Tenant, Property, Lease, ExpenseProfile, IncomeProfile, Landlord, Unit , EarmarkedTransaction, ParsedTransaction
from datetime import date
from django.urls import reverse

class TenantModelTest(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            name="John Doe",
            phone_number="123456789",
            email="john@example.com",
            address="123 Main St",
            iban="DE1234567890",
            bic="ABCDEF12",
        )

    def test_tenant_creation(self):
        self.assertEqual(self.tenant.name, "John Doe")
        self.assertEqual(self.tenant.email, "john@example.com")


class PropertyModelTest(TestCase):
    def setUp(self):
        self.landlord = Landlord.objects.create(name="Jane Smith")
        self.property = Property.objects.create(
            name="Sunrise Apartments",
            property_type="residential",
            street="Sunset Blvd",
            building_no="42",
            city="Berlin",
            zip="10117",
            country="Germany"
        )
        self.property.landlords.add(self.landlord)

    def test_property_creation(self):
        self.assertEqual(self.property.name, "Sunrise Apartments")
        self.assertEqual(self.property.city, "Berlin")
        self.assertIn(self.landlord, self.property.landlords.all())


class LeaseModelTest(TestCase):
    def setUp(self):
        self.property = Property.objects.create(
            name="Hill View",
            property_type="residential",
            street="Greenway St",
            building_no="7",
            city="Munich",
            zip="80331",
            country="Germany"
        )
        self.unit = Unit.objects.create(
            property=self.property,
            unit_name="Unit 1A",
            floor_area=85,
            rooms=3,
            baths=1,
            market_rent=1200
        )
        self.tenant = Tenant.objects.create(name="Michael Scott")
        self.lease = Lease.objects.create(
            property=self.property,
            unit=self.unit,
            tenant=self.tenant,
            start_date=date.today(),
            deposit_amount=2400,
            rent=1200  # Fix added here
        )

    def test_lease_creation(self):
        self.assertEqual(self.lease.unit.unit_name, "Unit 1A")
        self.assertEqual(self.lease.tenant.name, "Michael Scott")
        self.assertEqual(self.lease.deposit_amount, 2400)
        self.assertEqual(self.lease.rent, 1200)  # New assertion


class ExpenseProfileModelTest(TestCase):
    def setUp(self):
        self.property = Property.objects.create(name="Riverside Complex")
        self.expense_profile = ExpenseProfile.objects.create(
            property=self.property,
            profile_name="Maintenance",
            transaction_type="maintenance_direct",
            amount=500,
            date=date.today(),
            recurring=True,
            frequency="monthly",
            account_name="Building Maintenance",
            ust=19
        )

    def test_expense_creation(self):
        self.assertEqual(self.expense_profile.profile_name, "Maintenance")
        self.assertEqual(self.expense_profile.transaction_type, "maintenance_direct")


class ViewTests(TestCase):
    def setUp(self):
        self.property = Property.objects.create(name="Ocean Towers")


    def test_properties_view(self):
        response = self.client.get(reverse("properties"))
        self.assertEqual(response.status_code, 200)

class test_earmarked_transaction_signal(TestCase):
    def setUp(self):
        self.property = Property.objects.create(name="Test Property")
        self.transaction = EarmarkedTransaction.objects.create(
            property=self.property,
            date="2025-01-01",
            amount=100,
            is_income=True,
            account_name="Test Account"
        )

    def test_earmarked_transaction_signal(self):
        self.assertEqual(ParsedTransaction.objects.count(), 1)