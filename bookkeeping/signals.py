from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import EarmarkedTransaction, ParsedTransaction, ExpenseProfile, IncomeProfile
from decimal import Decimal
import logging
from .models import Lease, IncomeProfile

logger = logging.getLogger(__name__)

def find_matching_profile(account_name, amount, property):
    """Find a matching profile by exact account name, amount, and property."""
    expense_profile = ExpenseProfile.objects.filter(
        account_name=account_name,
        property=property,
        amount=amount
    ).first()

    income_profile = IncomeProfile.objects.filter(
        account_name=account_name,
        property=property,
        amount=amount
    ).first()

    return expense_profile, income_profile



@receiver(post_save, sender=EarmarkedTransaction)
def process_earmarked_transaction(sender, instance, created, **kwargs):
    if created:
        try:
            if instance.property:
                expense_profile, income_profile = find_matching_profile(
                    instance.account_name,
                    instance.amount,
                    instance.property
                )
            else:
                logger.warning(f"Property is None for EarmarkedTransaction {instance.id}")
                return

            if expense_profile:
                logger.info(f"Matched EarmarkedTransaction {instance.id} → ExpenseProfile {expense_profile.id}")
                parsed_txn = ParsedTransaction(
                    date=instance.date,
                    account_name=instance.account_name,
                    booking_no=instance.booking_no,  # ✅ use booking_no from EarmarkedTransaction
                    transaction_type=expense_profile.transaction_type,
                    related_property=instance.property,
                    unit_name=expense_profile.lease.unit.unit_name if expense_profile.lease and expense_profile.lease.unit else None,
                    ust_type=expense_profile.ust,
                    betrag_brutto=instance.amount,
                    is_income=instance.is_income,
                    tenant=expense_profile.lease.tenants.first().name if expense_profile.lease and expense_profile.lease.tenants.exists() else None,
                    invoice=expense_profile.invoice
                )
                parsed_txn.save()
                instance.delete()

            elif income_profile:
                logger.info(f"Matched EarmarkedTransaction {instance.id} → IncomeProfile {income_profile.id}")
                parsed_txn = ParsedTransaction(
                    date=instance.date,
                    account_name=instance.account_name,
                    booking_no=instance.booking_no,  # ✅ use booking_no from EarmarkedTransaction
                    transaction_type=income_profile.transaction_type,
                    related_property=instance.property,
                    unit_name=income_profile.lease.unit.unit_name if income_profile.lease and income_profile.lease.unit else None,
                    ust_type=income_profile.ust,
                    betrag_brutto=instance.amount,
                    is_income=instance.is_income,
                    tenant=income_profile.lease.tenants.first().name if income_profile.lease and income_profile.lease.tenants.exists() else None,
                )
                parsed_txn.save()
                instance.delete()
            else:
                logger.info(f"No profile matched for EarmarkedTransaction {instance.id}")
        except Exception as e:
            logger.error(f"Error processing EarmarkedTransaction {instance.id}: {str(e)}")





@receiver(post_save, sender=ExpenseProfile)
def match_earmarked_transactions_for_expense(sender, instance, created, **kwargs):
    if created:
        logger.info(f"🧾 Created new ExpenseProfile {instance.id}")
        print(f"[DEBUG] New ExpenseProfile: {instance.id}, account_name: {instance.account_name}, property: {instance.property.id}, amount: {instance.amount}")

        earmarked_transactions = EarmarkedTransaction.objects.filter(
            account_name=instance.account_name,
            property=instance.property
        )

        print(f"[DEBUG] Found {earmarked_transactions.count()} EarmarkedTransaction(s) matching account_name and property")

        for txn in earmarked_transactions:
            try:
                matched_profile, _ = find_matching_profile(txn.account_name, txn.amount, txn.property)
                if matched_profile and matched_profile.id == instance.id:
                    print(txn.booking_no)
                    ParsedTransaction.objects.create(
                        date=txn.date,
                        account_name=txn.account_name,
                        booking_no= txn.booking_no ,
                        transaction_type=instance.transaction_type,
                        related_property=txn.property,
                        unit_name=instance.lease.unit.unit_name if instance.lease and instance.lease.unit else None,
                        ust_type=instance.ust,
                        betrag_brutto=txn.amount,
                        is_income=txn.is_income,
                        tenant=instance.lease.tenants.first().name if instance.lease and instance.lease.tenants.exists() else None,
                        invoice=instance.invoice
                    )
                    txn.delete()
                else:
                    print(f"[DEBUG] ❌ No profile matched or profile.id mismatch for EarmarkedTransaction {txn.id}")

            except Exception as e:
                logger.error(f"🚨 Error processing EarmarkedTransaction {txn.id} → ExpenseProfile {instance.id}: {e}")
                print(f"[DEBUG] Exception occurred: {e}")


@receiver(post_save, sender=IncomeProfile)
def match_earmarked_transactions_for_income(sender, instance, created, **kwargs):
    if created:
        logger.info(f"Checking existing EarmarkedTransactions for new IncomeProfile {instance.id}")
        earmarked_transactions = EarmarkedTransaction.objects.filter(
            account_name=instance.account_name,
            property=instance.property
        )

        for txn in earmarked_transactions:
            try:
                _, matched_profile = find_matching_profile(txn.account_name, txn.amount, txn.property)
                if matched_profile and matched_profile.id == instance.id:
                    logger.info(f"Matched EarmarkedTransaction {txn.id} → IncomeProfile {instance.id}")
                    ParsedTransaction.objects.create(
                        date=txn.date,
                        account_name=txn.account_name,
                        booking_no=txn.booking_no,  
                        transaction_type=instance.transaction_type,
                        related_property=txn.property,
                        unit_name=instance.lease.unit.unit_name if instance.lease and instance.lease.unit else None,
                        ust_type=instance.ust,
                        betrag_brutto=txn.amount,
                        is_income=txn.is_income,
                        tenant=instance.lease.tenants.first().name if instance.lease and instance.lease.tenants.exists() else None,
                    )
                    txn.delete()
            except Exception as e:
                logger.error(f"Error linking EarmarkedTransaction {txn.id} to IncomeProfile {instance.id}: {e}")


@receiver(post_save, sender=Lease)
def create_income_profiles_for_lease(sender, instance, created, **kwargs):
    if created:  # Only handle newly created leases
        # Map UST types (if necessary)
        ust_mapping = {
            'Nicht': 0,  # No VAT
            'Voll': 19,  # Full VAT
            'Teilw': 7   # Partial VAT
        }

        # Convert ust_type if it's a string
        ust_value = ust_mapping.get(instance.ust_type, 19)  # Default to 'Voll' (19%)

        # Loop through all tenants in the lease
        for tenant in instance.tenants.all():
            # Create income profile for deposit (if applicable)
            if instance.deposit_amount > 0:
                IncomeProfile.objects.create(
                    lease=instance,
                    property=instance.property,
                    transaction_type='security_deposit',
                    amount=instance.deposit_amount / instance.tenants.count(),  # Split deposit among tenants
                    date=instance.start_date,  # Use the lease's start date
                    account_name=tenant.name,
                    recurring=False,  # Deposits are not recurring
                    ust=ust_value  # Use the mapped numeric UST value
                )

            # Create income profile for rent
            IncomeProfile.objects.create(
                lease=instance,
                property=instance.property,
                transaction_type='rent',
                amount=instance.rent / instance.tenants.count(),  # Split rent among tenants
                date=instance.start_date,  # Use the lease's start date
                account_name=tenant.name,
                recurring=True,  # Rent is typically recurring
                frequency='monthly',
                ust=ust_value  # Use the mapped numeric UST value
            )

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import Lease, Property, Unit
from decimal import Decimal


def recalculate_partial_tax_rate(property_obj):
    if not property_obj.auto_calculate_tax:
        return

    leases = Lease.objects.filter(property=property_obj)

    if property_obj.tax_calculation_method == 'sq_meterage':
        area_with_ust = sum(
            lease.unit.floor_area for lease in leases
            if lease.ust_type == 'Mit' and lease.unit and lease.unit.floor_area
        )
        total_area = sum(
            lease.unit.floor_area for lease in leases
            if lease.unit and lease.unit.floor_area
        )
        new_rate = (area_with_ust / total_area) * 100 if total_area > 0 else 0.0

    elif property_obj.tax_calculation_method == 'income':
        income_with_ust = sum(
            (lease.rent + (lease.additional_costs or 0) + lease.deposit_amount)
            for lease in leases if lease.ust_type == 'Mit'
        )
        total_income = sum(
            (lease.rent + (lease.additional_costs or 0) + lease.deposit_amount)
            for lease in leases
        )
        new_rate = (income_with_ust / total_income) * 100 if total_income > 0 else 0.0

    else:
        return  # Manual entry, skip

    property_obj.partial_tax_rate = Decimal(str(round(new_rate, 2)))
    property_obj.save()


@receiver(post_save, sender=Lease)
def on_lease_saved(sender, instance, **kwargs):
    recalculate_partial_tax_rate(instance.property)


@receiver(post_delete, sender=Lease)
def on_lease_deleted(sender, instance, **kwargs):
    recalculate_partial_tax_rate(instance.property)


@receiver(post_save, sender=Unit)
def on_unit_saved(sender, instance, **kwargs):
    property_obj = instance.property
    recalculate_partial_tax_rate(property_obj)