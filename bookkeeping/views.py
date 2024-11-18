import pdfplumber
import fitz  # PyMuPDF
import re
from django.shortcuts import render, redirect
from .models import (
    EarmarkedTransaction, ParsedTransaction, Property, Tenant, ExpenseProfile
)
from datetime import datetime


# Dashboard: Displays Earmarked and Parsed Transactions
def dashboard(request):
    earmarked = EarmarkedTransaction.objects.all()
    parsed = ParsedTransaction.objects.all()
    return render(request, 'bookkeeping/dashboard.html', {
        'earmarked': earmarked,
        'parsed': parsed
    })


# Upload Bank Statement
def upload_bank_statement(request):
    if request.method == 'POST' and request.FILES.get('statement'):
        statement = request.FILES['statement']
        earmarked_transactions = []

        def extract_text_with_fallback(page, statement):
            # Try pdfplumber first
            text = page.extract_text()
            if not text:
                print("Trying fallback extraction with PyMuPDF...")
                # Reset file pointer for PyMuPDF
                statement.seek(0)
                with fitz.open(stream=statement.read(), filetype="pdf") as pdf:
                    page_num = page.page_number - 1
                    text = pdf[page_num].get_text("text")
            return text

        with pdfplumber.open(statement) as pdf:
            for page_number, page in enumerate(pdf.pages):
                # Extract text from actual PDF pages
                text = extract_text_with_fallback(page, statement)
                if not text:
                    print(f"No text found on page {page_number + 1} after fallback.")
                    continue

                print(f"Processing page {page_number + 1}...")
                # Split text into lines
                lines = text.split('\n')
                current_transaction = {}
                multiline_description = []

                for line_number, line in enumerate(lines):
                    line = line.strip()
                    if not line:
                        continue  # Skip empty lines

                    # Skip lines that are not valid transactions
                    if "Alter Kontostand vom" in line:
                        print(f"Skipping invalid transaction line: {line}")
                        continue

                    # Debugging: Log each line
                    print(f"Page {page_number + 1}, Line {line_number + 1}: {line}")

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
                            amount_match = re.search(r"-?\d{1,3}(?:\.\d{3})*,\d{2}-?", col)
                            if amount_match:
                                amount_str = amount_match.group(0).replace('.', '').replace(',', '.')
                                current_transaction['amount'] = abs(float(amount_str.strip('-')))
                                # Determine if it's income or expense based on the `-` at the end
                                current_transaction['is_income'] = not col.strip().endswith('-')
                                break

                    elif current_transaction:
                        # Append additional description lines
                        multiline_description.append(line)

                # Save the last transaction on the page
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
                        print(f"Error saving last transaction on page {page_number + 1}: {e}")

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
