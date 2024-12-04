from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import EarmarkedTransaction, ParsedTransaction, ExpenseProfile
from datetime import datetime

@receiver(post_save, sender=EarmarkedTransaction)
def process_earmarked_transaction(sender, instance, created, **kwargs):
    if created:  # Process only new transactions
        try:
            # Match account_name with ExpenseProfile
            expense_profile = ExpenseProfile.objects.filter(account_name=instance.account_name).first()
            
            if expense_profile:
                # Create ParsedTransaction
                parsed_txn = ParsedTransaction(
                    date=instance.date,
                    account_name=instance.account_name,
                    gggkto=expense_profile,
                    betrag_brutto=instance.amount
                )
                # Save the ParsedTransaction to calculate fields
                parsed_txn.save()
                # Link the ParsedTransaction back to the ExpenseProfile
                expense_profile.transactions.add(parsed_txn)
                # Optionally delete the EarmarkedTransaction after processing
                instance.delete()
            else:
                print(f"No ExpenseProfile found for account name: {instance.account_name}")

        except Exception as e:
            print(f"Error processing EarmarkedTransaction: {e}")


@receiver(post_save, sender=ExpenseProfile)
def match_earmarked_transactions(sender, instance, created, **kwargs):
    if created:
        # Match existing earmarked transactions
        earmarked_transactions = EarmarkedTransaction.objects.filter(account_name=instance.account_name)
        
        for txn in earmarked_transactions:
            try:
                # Create ParsedTransaction
                parsed_txn = ParsedTransaction(
                    date=txn.date,  # Convert date from string
                    account_name=txn.account_name,
                    gggkto=instance,
                    betrag_brutto=txn.amount
                )
                parsed_txn.save()
                # Link the ParsedTransaction to the ExpenseProfile
                instance.transactions.add(parsed_txn)
                # Delete the processed EarmarkedTransaction
                txn.delete()
            except Exception as e:
                print(f"Error processing EarmarkedTransaction for ExpenseProfile: {e}")
