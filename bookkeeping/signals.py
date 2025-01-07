from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import EarmarkedTransaction, ParsedTransaction, ExpenseProfile, IncomeProfile
from decimal import Decimal


def find_matching_profile(account_name, amount, property):
    """Attempt to find a matching profile by account name, amount, and property."""
    tolerance = Decimal('1.00')  # Allow ±1 unit tolerance

    # Try matching by account name, amount, and property
    expense_profile = ExpenseProfile.objects.filter(
        account_name=account_name,
        property=property,
        amount__gte=amount - tolerance,
        amount__lte=amount + tolerance
    ).first()

    income_profile = IncomeProfile.objects.filter(
        account_name=account_name,
        property=property,
        amount__gte=amount - tolerance,
        amount__lte=amount + tolerance
    ).first()

    return expense_profile, income_profile


@receiver(post_save, sender=EarmarkedTransaction)
def process_earmarked_transaction(sender, instance, created, **kwargs):
    if created:  # Process only new transactions
        try:
            # Match profiles by account_name, amount, and property
            expense_profile, income_profile = find_matching_profile(
                instance.account_name,
                instance.amount,
                instance.property
            )

            if expense_profile:
                print(f"Processing EarmarkedTransaction: {instance.id} for ExpenseProfile: {expense_profile.id}")
                parsed_txn = ParsedTransaction(
                    date=instance.date,
                    account_name=instance.account_name,
                    booking_no=expense_profile.booking_no,
                    transaction_type=expense_profile.transaction_type,
                    related_property=instance.property,
                    unit_name=expense_profile.lease.unit.unit_name if expense_profile.lease and expense_profile.lease.unit else None,
                    ust_type=expense_profile.ust,
                    betrag_brutto=instance.amount,
                    is_income=instance.is_income,
                    tenant=expense_profile.lease.tenant.name if expense_profile.lease and expense_profile.lease.tenant else None,
                )
                parsed_txn.save()
                instance.delete()

            elif income_profile:
                print(f"Processing EarmarkedTransaction: {instance.id} for IncomeProfile: {income_profile.id}")
                parsed_txn = ParsedTransaction(
                    date=instance.date,
                    account_name=instance.account_name,
                    booking_no=income_profile.booking_no,
                    transaction_type=income_profile.transaction_type,
                    related_property=instance.property,
                    unit_name=income_profile.lease.unit.unit_name if income_profile.lease and income_profile.lease.unit else None,
                    ust_type=income_profile.ust,
                    betrag_brutto=instance.amount,
                    is_income=instance.is_income,
                    tenant=income_profile.lease.tenant.name if income_profile.lease and income_profile.lease.tenant else None,
                )
                parsed_txn.save()
                instance.delete()
            else:
                print(f"No matching profile found for EarmarkedTransaction: {instance.id} with property {instance.property}")

        except Exception as e:
            print(f"Error processing EarmarkedTransaction (ID: {instance.id}): {e}")


@receiver(post_save, sender=ExpenseProfile)
def match_earmarked_transactions_for_expense(sender, instance, created, **kwargs):
    if created:
        print(f"Processing new ExpenseProfile: {instance.id}")
        earmarked_transactions = EarmarkedTransaction.objects.filter(
            account_name=instance.account_name,
            property=instance.property
        )

        for txn in earmarked_transactions:
            try:
                # Match by amount and account name
                if txn.amount == instance.amount:
                    print(f"Processing EarmarkedTransaction: {txn.id} for ExpenseProfile: {instance.id}")
                    parsed_txn = ParsedTransaction(
                        date=txn.date,
                        account_name=txn.account_name,
                        booking_no=instance.booking_no,
                        transaction_type=instance.transaction_type,
                        related_property=txn.property,
                        unit_name=instance.lease.unit.unit_name if instance.lease and instance.lease.unit else None,
                        ust_type=instance.ust,
                        betrag_brutto=txn.amount,
                        is_income=txn.is_income,
                        tenant=instance.lease.tenant.name if instance.lease and instance.lease.tenant else None,
                    )
                    parsed_txn.save()
                    txn.delete()

            except Exception as e:
                print(f"Error processing EarmarkedTransaction (ID: {txn.id}) for ExpenseProfile (ID: {instance.id}): {e}")


@receiver(post_save, sender=IncomeProfile)
def match_earmarked_transactions_for_income(sender, instance, created, **kwargs):
    if created:
        print(f"Processing new IncomeProfile: {instance.id}")
        earmarked_transactions = EarmarkedTransaction.objects.filter(
            account_name=instance.account_name,
            property=instance.property
        )

        for txn in earmarked_transactions:
            try:
                # Match by amount and account name
                if txn.amount == instance.amount:
                    print(f"Processing EarmarkedTransaction: {txn.id} for IncomeProfile: {instance.id}")
                    parsed_txn = ParsedTransaction(
                        date=txn.date,
                        account_name=txn.account_name,
                        booking_no=instance.booking_no,
                        transaction_type=instance.transaction_type,
                        related_property=txn.property,
                        unit_name=instance.lease.unit.unit_name if instance.lease and instance.lease.unit else None,
                        ust_type=instance.ust,
                        betrag_brutto=txn.amount,
                        is_income=txn.is_income,
                        tenant=instance.lease.tenant.name if instance.lease and instance.lease.tenant else None,
                    )
                    parsed_txn.save()
                    txn.delete()

            except Exception as e:
                print(f"Error processing EarmarkedTransaction (ID: {txn.id}) for IncomeProfile (ID: {instance.id}): {e}")
