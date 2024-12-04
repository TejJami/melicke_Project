import pdfplumber
import fitz  # PyMuPDF
import re
from django.shortcuts import render, redirect
from .models import (
    EarmarkedTransaction, ParsedTransaction, 
    Property, Tenant, ExpenseProfile, Unit, 
    Landlord, Lease , IncomeProfile
)
from django.shortcuts import get_object_or_404
from datetime import datetime
import PyPDF2
from io import BytesIO
import openpyxl
from django.http import HttpResponse
from django.forms import modelformset_factory
from django.forms import model_to_dict
from django.http import JsonResponse


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

                            # Validate the parsed date matches or is within the logical range of `Buchungsdatum`
                            if formatted_parsed_date != formatted_buchungsdatum:
                                print(f"Invalid transaction date {formatted_parsed_date} for Buchungsdatum {formatted_buchungsdatum}. Skipping.")
                                continue  # Skip invalid transaction
                        except ValueError as e:
                            print(f"Error parsing transaction date {parsed_date}: {e}")
                            continue  # Skip invalid transaction

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
        # try:
        #     EarmarkedTransaction.objects.bulk_create(earmarked_transactions)
        # except Exception as e:
        #     print(f"Error during bulk_create: {e}")
        for txn in earmarked_transactions:
            txn.save()  # This will trigger the `post_save` signal


        return redirect('dashboard')

    return render(request, 'bookkeeping/upload_statement.html')

#################################################################

# Properties
def properties(request):
    properties = Property.objects.all()
    landlords = Landlord.objects.all()  # Fetch all landlords for the dropdown
    return render(request, 'bookkeeping/properties.html', {
        'properties': properties,
        'landlords': landlords,
    })

# Add Property
def add_property(request):
    if request.method == 'POST':
        # Get property fields
        property_type = request.POST.get('property_type')
        name = request.POST.get('name')
        street = request.POST.get('street')
        building_no = request.POST.get('building_no')
        city = request.POST.get('city')
        zip_code = request.POST.get('zip')
        country = request.POST.get('country')
        landlord_ids = request.POST.getlist('landlords')

        # Create the Property object
        property_obj = Property.objects.create(
            property_type=property_type,
            name=name,
            street=street,
            building_no=building_no,
            city=city,
            zip=zip_code,
            country=country,
        )
        property_obj.landlords.set(landlord_ids)  # Set landlords for the property

        # Handle Units
        unit_data_keys = [key for key in request.POST.keys() if key.startswith('units-')]
        unit_data = {}

        # Organize unit data
        for key in unit_data_keys:
            match = re.match(r'units-(\d+)-(.+)', key)
            if match:
                unit_index, field_name = match.groups()
                if unit_index not in unit_data:
                    unit_data[unit_index] = {}
                unit_data[unit_index][field_name] = request.POST.get(key)

        # Create Unit objects
        for unit_index, unit_fields in unit_data.items():
            if unit_fields.get('unit_name'):  # Check if unit has a name (to avoid blank entries)
                Unit.objects.create(
                    property=property_obj,
                    unit_name=unit_fields.get('unit_name'),
                    floor_area=unit_fields.get('floor_area'),
                    rooms=unit_fields.get('rooms'),
                    baths=unit_fields.get('baths'),
                    market_rent=unit_fields.get('market_rent'),
                )

        return redirect('properties')

    landlords = Landlord.objects.all()

    return render(request, 'bookkeeping/add_property.html', {
        'landlords': landlords,
    })

# Edit Property
def edit_property(request, pk):
    property_obj = get_object_or_404(Property, id=pk)
    UnitFormSet = modelformset_factory(Unit, fields=('unit_name', 'floor_area', 'rooms', 'baths', 'market_rent'), extra=0, can_delete=True)

    if request.method == 'POST':
        # Update the main property fields
        property_obj.property_type = request.POST.get('property_type')
        property_obj.name = request.POST.get('name')
        property_obj.street = request.POST.get('street')
        property_obj.building_no = request.POST.get('building_no')
        property_obj.city = request.POST.get('city')
        property_obj.zip = request.POST.get('zip')
        property_obj.country = request.POST.get('country')

        # Update landlords
        landlord_ids = request.POST.getlist('landlords')
        property_obj.landlords.set(landlord_ids)

        # Save the property
        property_obj.save()

        # Process the formset for existing units
        unit_formset = UnitFormSet(request.POST, queryset=property_obj.units.all(), prefix='units')
        if unit_formset.is_valid():
            units = unit_formset.save(commit=False)
            # Save updated and existing units
            for unit in units:
                unit.property = property_obj
                unit.save()

            # Delete any units marked for deletion
            for deleted_unit in unit_formset.deleted_objects:
                deleted_unit.delete()
        else:
            print(unit_formset.errors)  # Debugging: print errors if formset validation fails

        # Process dynamically added units
        unit_data_keys = [key for key in request.POST.keys() if key.startswith('units-')]
        print("unit_data_keys",unit_data_keys)
        new_unit_data = {}

        for key in unit_data_keys:
            match = re.match(r'units-(\d+)-(.+)', key)
            if match:
                unit_index, field_name = match.groups()
                if unit_index not in new_unit_data:
                    new_unit_data[unit_index] = {}
                new_unit_data[unit_index][field_name] = request.POST.get(key)

        for unit_index, unit_fields in new_unit_data.items():
            # Ensure all required fields are present and create new units
            unit_name = unit_fields.get('unit_name')
            floor_area = unit_fields.get('floor_area', '0')  # Default to '0' if missing
            rooms = unit_fields.get('rooms', '0')  # Default to '0' if missing
            baths = unit_fields.get('baths', '0')  # Default to '0' if missing
            market_rent = unit_fields.get('market_rent', '0.0')  # Default to '0.0' if missing

            if unit_name:  # Only create units with a valid name
                Unit.objects.create(
                    property=property_obj,
                    unit_name=unit_name,
                    floor_area=floor_area,
                    rooms=rooms,
                    baths=baths,
                    market_rent=market_rent,
                )

        return redirect('properties')  # Redirect to properties list after saving

    # Prepopulate the formsets for existing units
    landlords = Landlord.objects.all()
    unit_formset = UnitFormSet(queryset=property_obj.units.all(), prefix='units')

    return render(request, 'bookkeeping/edit_property.html', {
        'property': property_obj,
        'landlords': landlords,
        'unit_formset': unit_formset,
    })

# Delete Property
def delete_property(request, pk):
    property_obj = get_object_or_404(Property, pk=pk)

    if request.method == 'POST':
        property_obj.delete()
        return redirect('properties')

    return render(request, 'bookkeeping/delete_property.html', {'property': property_obj})

#################################################################

# Tenants
def tenants(request):
    tenants = Tenant.objects.all()
    properties = Property.objects.all() 

    return render(request, 'bookkeeping/tenants.html', 
    {'tenants': tenants,
    'properties': properties
    }
    )

# Add Tenant
def add_tenant(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        iban = request.POST.get('iban')


        # Create the tenant
        Tenant.objects.create(name=name, iban=iban)
        return redirect('tenants')

    # Retrieve all properties for the dropdown
    properties = Property.objects.all()
    return render(request, 'bookkeeping/add_tenant.html', {'properties': properties})

# Edit Tenant
def edit_tenant(request, pk):
    tenant = get_object_or_404(Tenant, id=pk)

    if request.method == 'POST':
        tenant.name = request.POST.get('name')
        tenant.iban = request.POST.get('iban')

        # Save the updated tenant
        tenant.save()
        return redirect('tenants')  # Redirect to the tenants list page

    # For GET requests, render the edit template with the tenant details
    return render(request, 'bookkeeping/edit_tenant.html', {'tenant': tenant})

# Delete Tenant
def delete_tenant(request, pk):
    tenant = get_object_or_404(Tenant, id=pk)

    if request.method == 'POST':
        tenant.delete()
        return redirect('tenants')

    return render(request, 'bookkeeping/delete_tenant.html', {'tenant': tenant})

#################################################################

# Expenses
def expenses(request):
    expenses = ExpenseProfile.objects.all()
    properties = Property.objects.all()
    units = Unit.objects.all()
    return render(request, 'bookkeeping/expenses.html', {
        'expenses': expenses,
        'properties': properties,
        'units': units,
    })

# Add Expense Profile
def add_expense_profile(request):
    if request.method == 'POST':
        profile_name = request.POST.get('profile_name')
        account_name = request.POST.get('account_name')
        ust = request.POST.get('ust')
        ust_sch = request.POST.get('ust_sch')
        property_id = request.POST.get('property')
        unit_id = request.POST.get('unit')

        property_obj = Property.objects.filter(id=property_id).first()
        unit_obj = Unit.objects.filter(id=unit_id).first()

        ExpenseProfile.objects.create(
            profile_name=profile_name,
            account_name=account_name,
            ust=ust,
            ust_sch=ust_sch,
            property=property_obj,
            unit=unit_obj,
        )
        return redirect('expenses')

    properties = Property.objects.all()
    units = Unit.objects.all()
    return render(request, 'bookkeeping/add_expense_profile.html', {
        'properties': properties,
        'units': units,
    })

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

#################################################################

# Units
def units(request):
    units = Unit.objects.select_related('property').all()
    properties = Property.objects.all()

    return render(request, 'bookkeeping/units.html',
     {'units': units,
        'properties': properties
     })

# Add Unit
def add_unit(request):
    if request.method == 'POST':
        property_id = request.POST.get('property')
        unit_name = request.POST.get('unit_name')
        floor_area = request.POST.get('floor_area')
        rooms = request.POST.get('rooms')
        baths = request.POST.get('baths')
        market_rent = request.POST.get('market_rent')

        # Ensure the property exists
        property_obj = get_object_or_404(Property, id=property_id)

        # Create the unit
        Unit.objects.create(
            property=property_obj,
            unit_name=unit_name,
            floor_area=floor_area,
            rooms=rooms,
            baths=baths,
            market_rent=market_rent,
        )
        return redirect('units')

    # Fetch properties for the dropdown
    properties = Property.objects.all()
    return render(request, 'bookkeeping/add_unit.html', {'properties': properties})


# Edit Unit
def edit_unit(request, pk):
    unit = get_object_or_404(Unit, id=pk)

    if request.method == 'POST':
        property_id = request.POST.get('property')
        unit.unit_name = request.POST.get('unit_name')
        unit.floor_area = request.POST.get('floor_area')
        unit.rooms = request.POST.get('rooms')
        unit.baths = request.POST.get('baths')
        unit.market_rent = request.POST.get('market_rent')

        # Ensure the property exists and update
        unit.property = get_object_or_404(Property, id=property_id)
        unit.save()

        return redirect('units')

    # Fetch properties for the dropdown
    properties = Property.objects.all()
    return render(request, 'bookkeeping/edit_unit.html', {
        'unit': unit,
        'properties': properties,
    })

# Delete Unit
def delete_unit(request, pk):
    unit = get_object_or_404(Unit, id=pk)

    if request.method == 'POST':
        unit.delete()
        return redirect('units')

    return render(request, 'bookkeeping/delete_unit.html', {'unit': unit})

#################################################################

# Landlords
def landlords(request):
    landlords = Landlord.objects.all()
    return render(request, 'bookkeeping/landlords.html', {'landlords': landlords})

# Add Landlord
def add_landlord(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        contact_info = request.POST.get('contact_info')
        iban = request.POST.get('iban')

        Landlord.objects.create(name=name, contact_info=contact_info, iban=iban)
        return redirect('landlords')

    return render(request, 'bookkeeping/add_landlord.html')

# Edit Landlord
def edit_landlord(request, pk):
    landlord = get_object_or_404(Landlord, id=pk)

    if request.method == 'POST':
        landlord.name = request.POST.get('name')
        landlord.contact_info = request.POST.get('contact_info')
        landlord.iban = request.POST.get('iban')
        landlord.save()

        return redirect('landlords')

    return render(request, 'bookkeeping/edit_landlord.html', {'landlord': landlord})

# Delete Landlord
def delete_landlord(request, pk):
    landlord = get_object_or_404(Landlord, id=pk)

    if request.method == 'POST':
        landlord.delete()
        return redirect('landlords')

    return render(request, 'bookkeeping/delete_landlord.html', {'landlord': landlord})

#################################################################

# Export Parsed Transactions
def export_parsed_transactions(request):
    # Create a workbook and a sheet
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Parsed Transactions"

    # Add header row
    headers = ["Date", "Account Name", "Gggkto", "Betrag Brutto", "Ust.", "Betrag Netto"]
    ws.append(headers)

    # Retrieve parsed transactions
    parsed_transactions = ParsedTransaction.objects.all()

    # Add data rows
    for transaction in parsed_transactions:
        ws.append([
            transaction.date,
            transaction.account_name,
            str(transaction.gggkto) if transaction.gggkto else "N/A",
            transaction.betrag_brutto,
            transaction.ust,
            transaction.betrag_netto,
        ])

    # Prepare the HTTP response
    response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response['Content-Disposition'] = 'attachment; filename=parsed_transactions.xlsx'

    # Save workbook to the response
    wb.save(response)
    return response

#################################################################

# leases
def leases(request):
    leases = Lease.objects.select_related('property', 'unit', 'tenant').prefetch_related('landlords').all()
    properties = Property.objects.all()
    units = Unit.objects.all()
    tenants = Tenant.objects.all()
    landlords = Landlord.objects.all()

    return render(request, 'bookkeeping/leases.html', {
        'leases': leases,
        'properties': properties,
        'units': units,
        'tenants': tenants,
        'landlords': landlords,
    })


# Add Lease
def add_lease(request):
    if request.method == 'POST':
        unit_id = request.POST.get('unit')
        tenant_id = request.POST.get('tenant')
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')
        ust_type = request.POST.get('ust_type')
        deposit_amount = request.POST.get('deposit_amount')

        # Fetch the unit and its associated property, landlords, and rent
        unit_obj = get_object_or_404(Unit, id=unit_id)
        property_obj = unit_obj.property
        landlords = property_obj.landlords.all()
        rent = unit_obj.market_rent  # Assume the Unit model has a rent field

        # Fetch tenant and related data
        tenant_obj = get_object_or_404(Tenant, id=tenant_id)
        account_name = tenant_obj.name
        iban = tenant_obj.iban

        # Create the lease
        lease = Lease.objects.create(
            property=property_obj,
            unit=unit_obj,
            tenant=tenant_obj,
            start_date=start_date,
            end_date=end_date,
            ust_type=ust_type,
            deposit_amount=deposit_amount,
            rent=rent,
            account_names=[account_name],
            ibans=[iban],
        )
        lease.landlords.set(landlords)
        lease.save()

        return redirect('leases')

    properties = Property.objects.all()
    units = Unit.objects.all()
    tenants = Tenant.objects.all()
    return render(request, 'bookkeeping/add_lease.html', {
        'properties': properties,
        'units': units,
        'tenants': tenants,
    })

# Edit Lease
def edit_lease(request, pk):
    lease = get_object_or_404(Lease, id=pk)

    if request.method == 'POST':
        lease.property = get_object_or_404(Property, id=request.POST.get('property'))
        lease.unit = get_object_or_404(Unit, id=request.POST.get('unit'))
        lease.tenant = get_object_or_404(Tenant, id=request.POST.get('tenant'))
        lease.start_date = request.POST.get('start_date')
        lease.end_date = request.POST.get('end_date')
        lease.ust_type = request.POST.get('ust_type')
        lease.deposit_amount = request.POST.get('deposit_amount')

        # Update landlords
        landlord_ids = request.POST.getlist('landlords')
        lease.landlords.set(landlord_ids)

        lease.save()
        return redirect('leases')

    properties = Property.objects.all()
    units = Unit.objects.all()
    tenants = Tenant.objects.all()
    landlords = Landlord.objects.all()
    return render(request, 'bookkeeping/edit_lease.html', {
        'lease': lease,
        'properties': properties,
        'units': units,
        'tenants': tenants,
        'landlords': landlords
    })

# Delete Lease
def delete_lease(request, pk):
    lease = get_object_or_404(Lease, id=pk)

    if request.method == 'POST':
        lease.delete()
        return redirect('leases')

    return render(request, 'bookkeeping/delete_lease.html', {'lease': lease})

#################################################################

# Income Profiles
def income_profiles(request):
    income_profiles = IncomeProfile.objects.select_related('lease').all()
    return render(request, 'bookkeeping/income_profiles.html', {
        'income_profiles': income_profiles,
    })

# Add Income Profile
def add_income_profile(request):
    if request.method == 'POST':
        lease_id = request.POST.get('lease')
        transaction_type = request.POST.get('transaction_type')
        amount = request.POST.get('amount')
        date = request.POST.get('date')
        recurring = request.POST.get('recurring') == 'on'
        frequency = request.POST.get('frequency') if recurring else None

        lease = get_object_or_404(Lease, id=lease_id)

        IncomeProfile.objects.create(
            lease=lease,
            transaction_type=transaction_type,
            amount=amount,
            date=date,
            recurring=recurring,
            frequency=frequency
        )
        return redirect('income_profiles')

    leases = Lease.objects.all()
    return render(request, 'bookkeeping/add_income_profile.html', {
        'leases': leases,
    })

# Edit Income Profile
def edit_income_profile(request, pk):
    income_profile = get_object_or_404(IncomeProfile, id=pk)

    if request.method == 'POST':
        income_profile.lease = get_object_or_404(Lease, id=request.POST.get('lease'))
        income_profile.transaction_type = request.POST.get('transaction_type')
        income_profile.amount = request.POST.get('amount')
        income_profile.date = request.POST.get('date')
        income_profile.recurring = request.POST.get('recurring') == 'on'
        income_profile.frequency = request.POST.get('frequency') if income_profile.recurring else None

        income_profile.save()
        return redirect('income_profiles')

    leases = Lease.objects.all()
    return render(request, 'bookkeeping/edit_income_profile.html', {
        'income_profile': income_profile,
        'leases': leases,
    })

# Delete Income Profile
def delete_income_profile(request, pk):
    income_profile = get_object_or_404(IncomeProfile, id=pk)

    if request.method == 'POST':
        income_profile.delete()
        return redirect('income_profiles')

    return render(request, 'bookkeeping/delete_income_profile.html', {'income_profile': income_profile})

# AJAX endpoint to fetch unit and tenant data
def fetch_unit_tenant_data(request):
    unit_id = request.GET.get('unit_id')
    tenant_id = request.GET.get('tenant_id')

    response = {}

    if unit_id:
        unit = get_object_or_404(Unit, id=unit_id)
        response['property_id'] = unit.property.id
        response['landlord_ids'] = list(unit.property.landlords.values_list('id', flat=True))
        response['rent'] = unit.market_rent

    if tenant_id:
        tenant = get_object_or_404(Tenant, id=tenant_id)
        response['account_name'] = tenant.name
        response['iban'] = tenant.iban

    return JsonResponse(response)