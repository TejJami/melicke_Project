import pdfplumber
from django.shortcuts import render, redirect
from .models import (
    EarmarkedTransaction, ParsedTransaction, Property, Tenant, ExpenseProfile
)
import pdfplumber
import re
from datetime import datetime

# Dashboard: Displays Earmarked and Parsed Transactions
def dashboard(request):
    earmarked = EarmarkedTransaction.objects.all()
    parsed = ParsedTransaction.objects.all()
    return render(request, 'bookkeeping/dashboard.html', {
        'earmarked': earmarked,
        'parsed': parsed
    })



def upload_bank_statement(request):
    if request.method == 'POST' and request.FILES.get('statement'):
        statement = request.FILES['statement']
        earmarked_transactions = []

        with pdfplumber.open(statement) as pdf:
            for page_number, page in enumerate(pdf.pages):
                text = page.extract_text()
                if not text:
                    continue

                # Split text into lines
                lines = text.split('\n')
                current_transaction = {}
                multiline_description = []

                for line in lines:
                    # Check for a date in `dd.mm` format
                    date_match = re.search(r"\d{2}\.\d{2}", line)
                    if date_match:
                        # Save the previous transaction if it exists
                        if current_transaction and 'amount' in current_transaction:
                            current_transaction['description'] = " ".join(multiline_description).strip()
                            try:
                                txn = EarmarkedTransaction(
                                    date=current_transaction['date'],
                                    account_name=current_transaction['account_name'],
                                    amount=current_transaction['amount'],
                                    is_income=current_transaction['is_income'],
                                    description=current_transaction['description'],
                                )
                                earmarked_transactions.append(txn)
                            except Exception as e:
                                print(f"Error saving transaction: {e}")

                        # Start a new transaction
                        current_transaction = {}
                        multiline_description = []

                        # Parse the date
                        current_transaction['date'] = date_match.group(0)

                        # Extract account name (text before the date)
                        account_name = line.split(date_match.group(0))[0].strip()
                        current_transaction['account_name'] = account_name

                        # Parse the amount and determine if it's income or expense
                        columns = re.split(r'\s{2,}', line)  # Splitting by whitespace columns
                        for col in columns:
                            amount_match = re.search(r"-?\d{1,3}(?:\.\d{3})*,\d{2}", col)
                            if amount_match:
                                amount_str = amount_match.group(0).replace('.', '').replace(',', '.')
                                current_transaction['amount'] = abs(float(amount_str))
                                # Determine if it's income or expense
                                if "zu Ihren Lasten" in line or "Lasten" in text:
                                    current_transaction['is_income'] = False
                                elif "zu Ihren Gunsten" in line or "Gunsten" in text:
                                    current_transaction['is_income'] = True
                                break

                    elif current_transaction:
                        # Append additional description lines
                        multiline_description.append(line.strip())

                # Save the last transaction
                if current_transaction and 'amount' in current_transaction:
                    current_transaction['description'] = " ".join(multiline_description).strip()
                    try:
                        txn = EarmarkedTransaction(
                            date=current_transaction['date'],
                            account_name=current_transaction['account_name'],
                            amount=current_transaction['amount'],
                            is_income=current_transaction['is_income'],
                            description=current_transaction['description'],
                        )
                        earmarked_transactions.append(txn)
                    except Exception as e:
                        print(f"Error saving last transaction: {e}")

        # Save all transactions to the database
        try:
            EarmarkedTransaction.objects.bulk_create(earmarked_transactions)
            print(f"Saved {len(earmarked_transactions)} transactions to the database.")
        except Exception as e:
            print(f"Error during bulk_create: {e}")

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