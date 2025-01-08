from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import EarmarkedTransaction, ExpenseProfile, IncomeProfile
from .tasks import process_earmarked_transaction_task, match_expense_task, match_income_task
import logging

logger = logging.getLogger(__name__)

def profile_exists(account_name, amount, property):
    return (
        ExpenseProfile.objects.filter(account_name=account_name, amount=amount, property=property).exists() or
        IncomeProfile.objects.filter(account_name=account_name, amount=amount, property=property).exists()
    )

@receiver(post_save, sender=EarmarkedTransaction)
def process_earmarked_transaction(sender, instance, created, **kwargs):
    if created and profile_exists(instance.account_name, instance.amount, instance.property):
        process_earmarked_transaction_task.delay(instance.id)
    else:
        logger.info(f"No matching profile found for EarmarkedTransaction {instance.id}. Skipping task.")

@receiver(post_save, sender=ExpenseProfile)
def match_earmarked_transactions_for_expense(sender, instance, created, **kwargs):
    if created:
        match_expense_task.delay(instance.id)

@receiver(post_save, sender=IncomeProfile)
def match_earmarked_transactions_for_income(sender, instance, created, **kwargs):
    if created:
        match_income_task.delay(instance.id)
