import pdfplumber
from django.shortcuts import render, redirect
from .models import (
    EarmarkedTransaction, ParsedTransaction, Property, Tenant, ExpenseProfile
)
import pdfplumber
import re
# Dashboard: Displays Earmarked and Parsed Transactions
def dashboard(request):
    earmarked = EarmarkedTransaction.objects.all()
    parsed = ParsedTransaction.objects.all()
    return render(request, 'bookkeeping/dashboard.html', {
        'earmarked': earmarked,
        'parsed': parsed
    })

def upload_bank_statement(request):
    if request.method == 'POST' and request.FILES['statement']:
        statement = request.FILES['statement']
        earmarked_transactions = []

        with pdfplumber.open(statement) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                lines = text.split('\n')

                # Regex patterns for matching dates and amounts
                date_pattern = r"\d{2}\.\d{2}\.\d{4}"  # German date format
                amount_pattern = r"\d+,\d{2}-?"  # German amount format

                current_transaction = {}

                for line in lines:
                    # Check for date in the line (start of a transaction)
                    date_match = re.search(date_pattern, line)

                    if date_match:
                        # Process the previous transaction (if any)
                        if current_transaction and 'amount' in current_transaction:
                            earmarked_transactions.append(
                                EarmarkedTransaction(
                                    date=current_transaction['date'],
                                    amount=current_transaction['amount'],
                                    description=current_transaction['description'],
                                    is_income=current_transaction['is_income'],
                                )
                            )
                            current_transaction = {}

                        # Extract date
                        transaction_date = date_match.group(0)  # e.g., "02.01.2023"
                        current_transaction['date'] = transaction_date

                        # Extract amount (income or expense)
                        amount_match = re.search(amount_pattern, line)
                        if amount_match:
                            amount_str = amount_match.group(0).replace('.', '').replace(',', '.').replace('-', '')
                            is_income = '-' not in amount_match.group(0)
                            current_transaction['amount'] = float(amount_str)
                            current_transaction['is_income'] = is_income
                        else:
                            # If no amount is found, skip this transaction
                            current_transaction['amount'] = 0.0
                            current_transaction['is_income'] = False

                        # Extract description
                        description = line.split(date_match.group(0))[-1].strip()
                        current_transaction['description'] = description

                    elif current_transaction:
                        # Append multi-line descriptions
                        current_transaction['description'] += " " + line.strip()

                # Save the last transaction if it has a valid amount
                if current_transaction and 'amount' in current_transaction:
                    earmarked_transactions.append(
                        EarmarkedTransaction(
                            date=current_transaction['date'],
                            amount=current_transaction['amount'],
                            description=current_transaction['description'],
                            is_income=current_transaction['is_income'],
                        )
                    )

        # Bulk save all transactions
        EarmarkedTransaction.objects.bulk_create(earmarked_transactions)
        return redirect('dashboard')

    return render(request, 'bookkeeping/upload_statement.html')

# Add Property
def add_property(request):
    if request.method == 'POST':
        name = request.POST['name']
        address = request.POST['address']
        Property.objects.create(name=name, address=address)
        return redirect('dashboard')
    return render(request, 'bookkeeping/add_property.html')

# Add Tenant
def add_tenant(request):
    if request.method == 'POST':
        name = request.POST['name']
        property_id = request.POST['property']
        iban = request.POST['iban']
        property = Property.objects.get(id=property_id)
        Tenant.objects.create(name=name, property=property, iban=iban)
        return redirect('dashboard')
    properties = Property.objects.all()
    return render(request, 'bookkeeping/add_tenant.html', {'properties': properties})

# Add Expense Profile
def add_expense_profile(request):
    if request.method == 'POST':
        tag = request.POST['tag']
        iban = request.POST['iban']
        ExpenseProfile.objects.create(tag=tag, iban=iban)
        return redirect('dashboard')
    return render(request, 'bookkeeping/add_expense_profile.html')

# Properties
def properties(request):
    properties = Property.objects.all()
    return render(request, 'bookkeeping/properties.html', {'properties': properties})

# Tenants
def tenants(request):
    tenants = Tenant.objects.all()
    return render(request, 'bookkeeping/tenants.html', {'tenants': tenants})

# Expenses
def expenses(request):
    expenses = ExpenseProfile.objects.all()
    return render(request, 'bookkeeping/expenses.html', {'expenses': expenses})