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
    if request.method == 'POST' and request.FILES.get('statement'):
        statement = request.FILES['statement']
        earmarked_transactions = []

        with pdfplumber.open(statement) as pdf:
            for page_number, page in enumerate(pdf.pages):
                text = page.extract_text()
                if not text:
                    continue
                
                lines = text.split('\n')
                date_pattern = r"\d{2}\.\d{2}"  # Matches "30.01"
                amount_pattern = r"-?\d{1,3}(?:\.\d{3})*,\d{2}"  # Matches "1.794,48"
                current_transaction = {}
                multiline_description = []

                for i, line in enumerate(lines):
                    date_match = re.search(date_pattern, line)
                    if date_match:
                        if current_transaction and 'amount' in current_transaction:
                            current_transaction['description'] = " ".join(multiline_description).strip()
                            txn = EarmarkedTransaction(
                                date=current_transaction['date'],
                                amount=current_transaction['amount'],
                                description=current_transaction['description'],
                                is_income=current_transaction['is_income'],
                                account_name=current_transaction.get('account_name', ''),
                            )
                            earmarked_transactions.append(txn)

                        current_transaction = {'date': date_match.group(0)}
                        multiline_description = []

                        if i > 0:
                            current_transaction['account_name'] = lines[i - 1].strip()

                        columns = re.split(r'\s{2,}', line)
                        if len(columns) > 1:
                            left_match = re.search(amount_pattern, columns[0])
                            right_match = re.search(amount_pattern, columns[-1])
                            if left_match:
                                amount_str = left_match.group(0).replace('.', '').replace(',', '.')
                                current_transaction['amount'] = abs(float(amount_str))
                                current_transaction['is_income'] = False
                            elif right_match:
                                amount_str = right_match.group(0).replace('.', '').replace(',', '.')
                                current_transaction['amount'] = abs(float(amount_str))
                                current_transaction['is_income'] = True

                    elif current_transaction:
                        multiline_description.append(line.strip())

                if current_transaction and 'amount' in current_transaction:
                    current_transaction['description'] = " ".join(multiline_description).strip()
                    txn = EarmarkedTransaction(
                        date=current_transaction['date'],
                        amount=current_transaction['amount'],
                        description=current_transaction['description'],
                        is_income=current_transaction['is_income'],
                        account_name=current_transaction.get('account_name', ''),
                    )
                    earmarked_transactions.append(txn)

        print("Transactions to be saved:")
        for txn in earmarked_transactions:
            print(txn.date, txn.amount, txn.description, txn.is_income, txn.account_name)

        try:
            EarmarkedTransaction.objects.bulk_create(earmarked_transactions)
            print(f"Saved {len(earmarked_transactions)} transactions.")
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