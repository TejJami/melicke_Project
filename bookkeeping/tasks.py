from celery import shared_task
from .models import EarmarkedTransaction, ParsedTransaction, ExpenseProfile, IncomeProfile
import logging

logger = logging.getLogger(__name__)

def find_matching_profile(account_name, amount, property):
    expense_profile = ExpenseProfile.objects.filter(
        account_name=account_name,
        amount=amount,
        property=property
    ).first()

    income_profile = IncomeProfile.objects.filter(
        account_name=account_name,
        amount=amount,
        property=property
    ).first()

    return expense_profile, income_profile


@shared_task
def process_earmarked_transaction_task(transaction_id):
    try:
        instance = EarmarkedTransaction.objects.filter(id=transaction_id).first()
        if not instance:
            logger.warning(f"EarmarkedTransaction with ID {transaction_id} not found.")
            return

        if not instance.property:
            logger.warning(f"No property for EarmarkedTransaction {instance.id}. Skipping.")
            return

        # Match by account_name, property, and exact amount
        expense_profile, income_profile = find_matching_profile(
            instance.account_name,
            instance.amount,
            instance.property
        )

        if not expense_profile and not income_profile:
            logger.info(f"No matching profile found for EarmarkedTransaction {instance.id}. Skipping.")
            return

        if expense_profile:
            ParsedTransaction.objects.create(
                date=instance.date,
                account_name=instance.account_name,
                booking_no=expense_profile.booking_no,
                transaction_type=expense_profile.transaction_type,
                related_property=instance.property,
                betrag_brutto=instance.amount,
                is_income=False
            )
            logger.info(f"EarmarkedTransaction {instance.id} processed for ExpenseProfile {expense_profile.id}.")
        elif income_profile:
            ParsedTransaction.objects.create(
                date=instance.date,
                account_name=instance.account_name,
                booking_no=income_profile.booking_no,
                transaction_type=income_profile.transaction_type,
                related_property=instance.property,
                betrag_brutto=instance.amount,
                is_income=True
            )
            logger.info(f"EarmarkedTransaction {instance.id} processed for IncomeProfile {income_profile.id}.")

        # Delete after processing
        instance.delete()

    except Exception as e:
        logger.error(f"Error processing EarmarkedTransaction {transaction_id}: {str(e)}")


@shared_task
def match_expense_task(expense_profile_id):
    from .models import EarmarkedTransaction, ParsedTransaction, ExpenseProfile
    try:
        expense_profile = ExpenseProfile.objects.get(id=expense_profile_id)
        earmarked_transactions = EarmarkedTransaction.objects.filter(
            account_name=expense_profile.account_name,
            property=expense_profile.property,
            amount=expense_profile.amount
        )
        
        for txn in earmarked_transactions:
            ParsedTransaction.objects.create(
                date=txn.date,
                account_name=txn.account_name,
                booking_no=expense_profile.booking_no,
                transaction_type=expense_profile.transaction_type,
                related_property=txn.property,
                unit_name=expense_profile.lease.unit.unit_name if expense_profile.lease else None,
                ust_type=expense_profile.ust,
                betrag_brutto=txn.amount,
                is_income=txn.is_income,
                tenant=expense_profile.lease.tenant.name if expense_profile.lease and expense_profile.lease.tenant else None,
            )
            txn.delete()
            logger.info(f"EarmarkedTransaction {txn.id} matched with ExpenseProfile {expense_profile.id}")
    
    except Exception as e:
        logger.error(f"Error matching expense profile {expense_profile_id}: {str(e)}")


@shared_task
def match_income_task(income_profile_id):
    from .models import EarmarkedTransaction, ParsedTransaction, IncomeProfile
    try:
        income_profile = IncomeProfile.objects.get(id=income_profile_id)
        earmarked_transactions = EarmarkedTransaction.objects.filter(
            account_name=income_profile.account_name,
            property=income_profile.property,
            amount=income_profile.amount
        )
        
        for txn in earmarked_transactions:
            ParsedTransaction.objects.create(
                date=txn.date,
                account_name=txn.account_name,
                booking_no=income_profile.booking_no,
                transaction_type=income_profile.transaction_type,
                related_property=txn.property,
                unit_name=income_profile.lease.unit.unit_name if income_profile.lease else None,
                ust_type=income_profile.ust,
                betrag_brutto=txn.amount,
                is_income=txn.is_income,
                tenant=income_profile.lease.tenant.name if income_profile.lease and income_profile.lease.tenant else None,
            )
            txn.delete()
            logger.info(f"EarmarkedTransaction {txn.id} matched with IncomeProfile {income_profile.id}")
    
    except Exception as e:
        logger.error(f"Error matching income profile {income_profile_id}: {str(e)}")
