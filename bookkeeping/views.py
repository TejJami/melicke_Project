import pdfplumber
import fitz  # PyMuPDF
import re
from django.shortcuts import render, redirect
from .models import (
    EarmarkedTransaction, ParsedTransaction, Property, Tenant, ExpenseProfile
)
from django.shortcuts import get_object_or_404
from datetime import datetime
import PyPDF2
from io import BytesIO

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
        current_buchungsdatum = None  # To store the current `Buchungsdatum`

        def split_pdf_into_pages(pdf_file):
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            pages = []

            for page_num in range(len(pdf_reader.pages)):
                pdf_writer = PyPDF2.PdfWriter()
                pdf_writer.add_page(pdf_reader.pages[page_num])

                # Save each page to a BytesIO object
                page_stream = BytesIO()
                pdf_writer.write(page_stream)
                page_stream.seek(0)
                pages.append(page_stream)

            return pages

        def extract_text_with_fallback(page_stream):
            text = None
            # Attempt pdfplumber first
            try:
                with pdfplumber.open(page_stream) as pdf:
                    text = pdf.pages[0].extract_text()
            except Exception as e:
                print(f"pdfplumber failed: {e}")

            if not text:
                # Use PyMuPDF (fitz) for fallback
                page_stream.seek(0)  # Reset the stream
                with fitz.open(stream=page_stream.read(), filetype="pdf") as pdf:
                    text = pdf[0].get_text("text")
            return text

        # Split the PDF into individual pages
        pages = split_pdf_into_pages(statement)

        for page_number, page_stream in enumerate(pages):
            text = extract_text_with_fallback(page_stream)
            if not text:
                print(f"No text found on page {page_number + 1} after fallback.")
                continue

            # Process the text for this page
            lines = text.split('\n')
            current_transaction = {}
            multiline_description = []

            for line_number, line in enumerate(lines):
                line = line.strip()
                if not line:
                    continue  # Skip empty lines

                # Check for `Buchungsdatum` to update the current reference date
                if "Buchungsdatum:" in line:
                    date_match = re.search(r"\d{2}\.\d{2}\.\d{4}", line)
                    if date_match:
                        current_buchungsdatum = date_match.group(0)
                        try:
                            # Convert `current_buchungsdatum` (DD.MM.YYYY) to Django date format (YYYY-MM-DD)
                            formatted_buchungsdatum = datetime.strptime(current_buchungsdatum, "%d.%m.%Y").date()
                        except ValueError as e:
                            print(f"Error parsing Buchungsdatum: {e}")
                            formatted_buchungsdatum = None  # Handle the error if needed
                    continue  # Skip to the next line

                # Skip invalid lines
                if (
                    "Alter Kontostand vom" in line or
                    "Neuer Kontostand vom" in line or
                    re.search(r"Kontostand", line, re.IGNORECASE) or
                    "Änderung Freistellungsauftrag" in line
                ):
                    continue

                # Check for valid transactions only if `current_buchungsdatum` is set
                if current_buchungsdatum:
                    # Check for a date in `dd.mm` format (e.g., `03.01`)
                    date_match = re.search(r"\d{2}\.\d{2}", line)
                    if date_match:
                        parsed_date = date_match.group(0)
                        try:
                            # Combine parsed date with the year from `formatted_buchungsdatum`
                            formatted_parsed_date = datetime.strptime(parsed_date, "%d.%m").date()
                            if formatted_buchungsdatum:
                                formatted_parsed_date = formatted_parsed_date.replace(year=formatted_buchungsdatum.year)
                        except ValueError as e:
                            print(f"Error parsing transaction date {parsed_date}: {e}")
                            formatted_parsed_date = formatted_buchungsdatum  # Fallback to Buchungsdatum

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

                        # Use the parsed date for the transaction
                        current_transaction['date'] = formatted_parsed_date

                        # Extract account name (text before the date)
                        account_name = line.split(parsed_date)[0].strip()
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
        profile_name = request.POST.get('profile_name')
        account_name = request.POST.get('account_name')
        ust = request.POST.get('ust')
        ust_sch = request.POST.get('ust_sch')

        # Create the new ExpenseProfile object
        ExpenseProfile.objects.create(
            profile_name=profile_name,
            account_name=account_name,
            ust=ust,
            ust_sch=ust_sch
        )

        # Redirect to the dashboard or expenses page after saving
        return redirect('expenses')

    return redirect('expenses')  # Fallback for GET requests (redirect to the expenses page)

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

# Edit Expense Profile
def edit_expense_profile(request):
    if request.method == 'POST':
        expense_id = request.POST.get('expense_id')
        profile_name = request.POST.get('profile_name')
        account_name = request.POST.get('account_name')
        ust = request.POST.get('ust')
        ust_sch = request.POST.get('ust_sch')

        # Update the expense profile
        expense = get_object_or_404(ExpenseProfile, id=expense_id)
        expense.profile_name = profile_name
        expense.account_name = account_name
        expense.ust = ust
        expense.ust_sch = ust_sch
        expense.save()

        return redirect('expenses')  # Redirect back to the expenses page

# Delete Expense Profile
def delete_expense_profile(request, pk):
    if request.method == 'POST':
        expense = get_object_or_404(ExpenseProfile, pk=pk)
        expense.delete()
        return redirect('expenses')  # Redirect back to the expenses page