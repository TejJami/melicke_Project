from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import EarmarkedTransaction, ParsedTransaction, ExpenseProfile, IncomeProfile,Tenant
from decimal import Decimal
import logging
from .models import Lease, IncomeProfile

logger = logging.getLogger(__name__)

def create_split_parsed_transactions(txn, profile):
    """
    Create multiple ParsedTransactions based on split_details.
    Skips 'account_balance' from transaction creation.
    """
    split_details = profile.split_details or {}
    base_booking = txn.booking_no

    # Only include actual transaction types in split_total, not 'account_balance'
    split_total = sum(Decimal(str(v)) for k, v in split_details.items() if k != "account_balance")
    full_total = sum(Decimal(str(v)) for v in split_details.values())

    if abs(Decimal(str(txn.amount)) - full_total) < Decimal("0.01"):
        idx = 1
        for tx_type, amt in split_details.items():
            if tx_type == "account_balance":
                continue  # Do not create ParsedTransaction for balance remainder
            ParsedTransaction.objects.create(
                date=txn.date,
                account_name=txn.account_name,
                booking_no=f"{base_booking}.{idx:02d}",
                transaction_type=tx_type,
                related_property=txn.property,
                unit_name=profile.lease.unit.unit_name if profile.lease and profile.lease.unit else None,
                ust_type=profile.ust,
                betrag_brutto=amt,
                is_income=txn.is_income,
                tenant=profile.lease.tenants.first().name if profile.lease and profile.lease.tenants.exists() else None,
            )
            idx += 1

        # Update tenant balance if 'account_balance' was stored
        remainder = Decimal(str(split_details.get("account_balance", 0)))
        if remainder > 0 and profile.lease and profile.lease.tenants.exists():
            tenant = profile.lease.tenants.first()
            tenant.balance += remainder
            tenant.save()

        txn.delete()
        return True
    else:
        txn.flagged_for_review = True
        txn.review_note = f"Split mismatch: expected {txn.amount}, got {full_total}"
        txn.save()
        return False


def generate_split_booking_nos(base_bn, count):
    """
    Given a base booking number like '0004', generate ['0004-A', '0004-B', ...] for the count.
    """
    suffixes = []
    for i in range(count):
        letter = chr(65 + i)  # 65 is ASCII for 'A'
        suffixes.append(f"{base_bn}-{letter}")
    return suffixes


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
    if not created:
        return

    try:
        if not instance.property:
            logger.warning(f"Property is None for EarmarkedTransaction {instance.id}")
            return

        expense_profile, income_profile = find_matching_profile(
            instance.account_name,
            instance.amount,
            instance.property
        )

        if expense_profile:
            ParsedTransaction.objects.create(
                date=instance.date,
                account_name=instance.account_name,
                booking_no=instance.booking_no,
                transaction_type=expense_profile.transaction_type,
                related_property=instance.property,
                unit_name=expense_profile.lease.unit.unit_name if expense_profile.lease and expense_profile.lease.unit else None,
                ust_type=expense_profile.ust,
                betrag_brutto=instance.amount,
                is_income=instance.is_income,
                tenant=expense_profile.lease.tenants.first().name if expense_profile.lease and expense_profile.lease.tenants.exists() else None,
                invoice=expense_profile.invoice
            )
            instance.delete()

        elif income_profile:
            if income_profile.split_details:
                split_details = income_profile.split_details
                full_total = sum(Decimal(str(v)) for v in split_details.values())
                transaction_keys = [k for k in split_details if k != "account_balance"]

                if abs(Decimal(str(instance.amount)) - full_total) < Decimal("0.01"):
                    suffixes = generate_split_booking_nos(instance.booking_no, len(transaction_keys))

                    i = 0
                    for tx_type, amt in split_details.items():
                        if tx_type == "account_balance":
                            continue

                        ParsedTransaction.objects.create(
                            date=instance.date,
                            account_name=instance.account_name,
                            booking_no=suffixes[i],
                            transaction_type=tx_type,
                            related_property=instance.property,
                            unit_name=income_profile.lease.unit.unit_name if income_profile.lease and income_profile.lease.unit else None,
                            ust_type=income_profile.ust,
                            betrag_brutto=amt,
                            is_income=instance.is_income,
                            tenant=income_profile.lease.tenants.first().name if income_profile.lease and income_profile.lease.tenants.exists() else None,
                        )
                        i += 1

                    # Add account_balance to tenant if present
                    balance_remainder = Decimal(str(split_details.get("account_balance", 0)))
                    if balance_remainder > 0 and income_profile.lease and income_profile.lease.tenants.exists():
                        tenant = income_profile.lease.tenants.first()
                        tenant.balance += balance_remainder
                        tenant.save()

                    instance.delete()
                else:
                    instance.flagged_for_review = True
                    instance.review_note = f"Split mismatch: expected {instance.amount}, got {full_total}"
                    instance.save()

            else:
                # Non-split income
                ParsedTransaction.objects.create(
                    date=instance.date,
                    account_name=instance.account_name,
                    booking_no=instance.booking_no,
                    transaction_type=income_profile.transaction_type,
                    related_property=instance.property,
                    unit_name=income_profile.lease.unit.unit_name if income_profile.lease and income_profile.lease.unit else None,
                    ust_type=income_profile.ust,
                    betrag_brutto=instance.amount,
                    is_income=instance.is_income,
                    tenant=income_profile.lease.tenants.first().name if income_profile.lease and income_profile.lease.tenants.exists() else None,
                )
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
    if not created:
        return

    logger.info(f"Checking existing EarmarkedTransactions for new IncomeProfile {instance.id}")
    earmarked_transactions = EarmarkedTransaction.objects.filter(
        account_name=instance.account_name,
        property=instance.property
    )

    for txn in earmarked_transactions:
        try:
            if instance.split_details:
                split_details = instance.split_details
                split_total = sum(Decimal(str(v)) for k, v in split_details.items() if k != "account_balance")
                full_total = sum(Decimal(str(v)) for v in split_details.values())

                if abs(Decimal(str(txn.amount)) - full_total) < Decimal("0.01"):
                    suffixes = generate_split_booking_nos(txn.booking_no, len([k for k in split_details if k != "account_balance"]))
                    i = 0
                    for tx_type, amt in split_details.items():
                        if tx_type == "account_balance":
                            continue
                        ParsedTransaction.objects.create(
                            date=txn.date,
                            account_name=txn.account_name,
                            booking_no=suffixes[i],
                            transaction_type=tx_type,
                            related_property=txn.property,
                            unit_name=instance.lease.unit.unit_name if instance.lease and instance.lease.unit else None,
                            ust_type=instance.ust,
                            betrag_brutto=amt,
                            is_income=txn.is_income,
                            tenant=instance.lease.tenants.first().name if instance.lease and instance.lease.tenants.exists() else None,
                        )
                        i += 1

                    # Update balance from 'account_balance' remainder
                    remainder = Decimal(str(split_details.get("account_balance", 0)))
                    if remainder > 0 and instance.lease and instance.lease.tenants.exists():
                        tenant = instance.lease.tenants.first()
                        tenant.balance += remainder
                        tenant.save()

                    txn.delete()
                else:
                    txn.flagged_for_review = True
                    txn.review_note = f"Split mismatch: expected {txn.amount}, got {full_total}"
                    txn.save()
            else:
                _, matched_profile = find_matching_profile(txn.account_name, txn.amount, txn.property)
                if matched_profile and matched_profile.id == instance.id:
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
            print(f"[DEBUG] Exception occurred: {e}")   


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