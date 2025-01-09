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
from decimal import Decimal
from datetime import datetime
from django.urls import reverse
from django.core.paginator import Paginator

# Dashboard: Displays Earmarked and Parsed Transactions
def dashboard(request):
    earmarked = EarmarkedTransaction.objects.all()
    parsed = ParsedTransaction.objects.all()
    properties = Property.objects.all()
    units = Unit.objects.all()
    leases = Lease.objects.all()
    return render(request, 'bookkeeping/dashboard.html', {
        'earmarked': earmarked,
        'parsed': parsed,
        'properties': properties,
        'units': units,
        'leases': leases,
    })

# Upload Bank Statement
def upload_bank_statement(request, property_id=None):
    property_obj = get_object_or_404(Property, id=property_id)  # Ensure property exists

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
                                    property=property_obj,  # Assign the property
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
                        property=property_obj,  # Assign the property
                    )
                    earmarked_transactions.append(txn)
                except Exception as e:
                    print(f"Error saving last transaction on page {page_number + 1}: {e}")

        # Save all transactions to the database
        for txn in earmarked_transactions:
            txn.save()  # This will trigger the `post_save` signal

        # Redirect to the property detail view with the dashboard tab
        return redirect(f"{reverse('property_detail', args=[property_id])}?tab=dashboard")

    return render(request, 'bookkeeping/upload_statement.html', {'property': property_obj})

#################################################################

# Properties
def properties(request):
    query = request.GET.get('q', '')
    properties = Property.objects.filter(name__icontains=query) if query else Property.objects.all()
    
    paginator = Paginator(properties, 6)  # Display 6 properties per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    landlords = Landlord.objects.all()
    return render(request, 'bookkeeping/properties.html', {
        'page_obj': page_obj,
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

        ust_type = request.POST.get('ust_type')

        # Create the Property object
        property_obj = Property.objects.create(
            property_type=property_type,
            name=name,
            street=street,
            building_no=building_no,
            city=city,
            zip=zip_code,
            country=country,
            ust_type=ust_type,
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

        property_obj.ust_type = request.POST.get('ust_type')

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

        return redirect('property_detail', property_id=pk)

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
    query = request.GET.get('q', '')
    tenants = Tenant.objects.all()

    if query:
        tenants = tenants.filter(name__icontains=query)  # Filter tenants by name

    return render(request, 'bookkeeping/tenants.html', {
        'tenants': tenants,
    })

# Add Tenant
def add_tenant(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        other_account_names = request.POST.get('other_account_names')
        phone_number = request.POST.get('phone_number')
        email = request.POST.get('email')
        address = request.POST.get('address')
        iban = request.POST.get('iban')
        bic = request.POST.get('bic')
        notes = request.POST.get('notes')

        # Create the tenant
        Tenant.objects.create(
            name=name,
            other_account_names=other_account_names,
            phone_number=phone_number,
            email=email,
            address=address,
            iban=iban,
            bic=bic,
            notes=notes,
        )
        return redirect('tenants')

    return render(request, 'bookkeeping/add_tenant.html')

# Edit Tenant
def edit_tenant(request, pk):
    tenant = get_object_or_404(Tenant, id=pk)

    if request.method == 'POST':
        tenant.name = request.POST.get('name')
        tenant.other_account_names = request.POST.get('other_account_names')
        tenant.phone_number = request.POST.get('phone_number')
        tenant.email = request.POST.get('email')
        tenant.address = request.POST.get('address')
        tenant.iban = request.POST.get('iban')
        tenant.bic = request.POST.get('bic')
        tenant.notes = request.POST.get('notes')

        tenant.save()
        return redirect('tenants')

    return render(request, 'bookkeeping/edit_tenant.html', {'tenant': tenant})

# Delete Tenant
def delete_tenant(request, pk):
    tenant = get_object_or_404(Tenant, id=pk)

    if request.method == 'POST':
        tenant.delete()
        return redirect('tenants')

    return render(request, 'bookkeeping/delete_tenant.html', {'tenant': tenant})

#################################################################

# Expense Profiles
def expense_profiles(request):
    properties = Property.objects.prefetch_related('leases', 'expense_profiles').all()
    return render(request, 'bookkeeping/expense_profiles.html', {
        'properties': properties,
    })

def add_expense_profile(request):
    if request.method == 'POST':
        data = request.POST
        lease_id = data.get('lease')
        property_id = data.get('property')
        amount = data.get('amount')
        date = data.get('date')
        recurring = data.get('recurring') == 'on'

        # Log the request data for debugging
        print("Request POST data:", data)

        # Validate Property ID
        property_obj = get_object_or_404(Property, id=property_id)

        # Fetch Lease if provided
        lease = Lease.objects.filter(id=lease_id).first() if lease_id else None

        # Determine UST dynamically
        ust = get_ust_from_lease_or_property(lease, property_obj)

        # Safely parse optional fields
        amount = safe_decimal(amount)
        date = safe_date(date)

        # Create Expense Profile
        ExpenseProfile.objects.create(
            lease=lease,
            property=property_obj,
            # profile_name=data.get('profile_name'),
            transaction_type=data.get('transaction_type'),
            amount=amount,
            date=date,
            recurring=recurring,
            frequency=data.get('frequency'),
            account_name=data.get('account_name'),
            ust=ust,
            booking_no=data.get('booking_no'),
        )
        return redirect(f"{reverse('property_detail', args=[property_obj.id])}?tab=expense")

    return redirect('dashboard')  # Default fallback


def edit_expense_profile(request, pk):
    expense = get_object_or_404(ExpenseProfile, id=pk)
    property_obj = expense.property

    if request.method == 'POST':
        data = request.POST
        lease_id = data.get('lease')
        amount = data.get('amount')
        date = data.get('date')
        recurring = data.get('recurring') == 'on'

        # Fetch Lease if provided
        lease = Lease.objects.filter(id=lease_id).first() if lease_id else None

        # Determine UST dynamically
        ust = get_ust_from_lease_or_property(lease, property_obj)

        # Update Expense Profile fields
        expense.lease = lease
        # expense.profile_name = data.get('profile_name')
        expense.transaction_type = data.get('transaction_type')
        expense.recurring = recurring
        expense.frequency = data.get('frequency') if recurring else None
        expense.account_name = data.get('account_name')
        expense.ust = ust
        expense.booking_no = data.get('booking_no')
        
        # Safely parse optional fields
        expense.amount = safe_decimal(amount)
        expense.date = safe_date(date)

        expense.save()
        return redirect(f"{reverse('property_detail', args=[property_obj.id])}?tab=expense")

    return redirect('dashboard')  # Default fallback


# Helper Functions

def get_ust_from_lease_or_property(lease, property_obj):
    """
    Determines UST based on lease if available, otherwise defaults to the property UST.
    """
    ust_mapping = {'Voll': 19, 'Teilw': 7, 'Nicht': 0}
    if lease and lease.ust_type:
        return ust_mapping.get(lease.ust_type, 0)
    return ust_mapping.get(property_obj.ust_type, 0)


def safe_decimal(value):
    """
    Safely converts a value to Decimal. Returns None if conversion fails.
    """
    try:
        return Decimal(value) if value else None
    except (ValueError, TypeError, Decimal.InvalidOperation):
        return None


def safe_date(value):
    """
    Safely parses a date string into a datetime object. Returns None if parsing fails.
    """
    try:
        return datetime.strptime(value, "%Y-%m-%d").date() if value else None
    except (ValueError, TypeError):
        return None
        
# Delete Expense Profile
def delete_expense_profile(request, pk):
    expense_profile = get_object_or_404(ExpenseProfile, id=pk)
    property_obj = expense_profile.property

    if request.method == 'POST':
        expense_profile.delete()
        return redirect(f"{reverse('property_detail', args=[property_obj.id])}?tab=expense")

    return redirect('dashboard')  # Default fallback

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

        # Redirect to property detail view
        return redirect('property_detail', property_id=property_obj.id)

    # Fetch properties for the dropdown
    properties = Property.objects.all()
    return render(request, 'bookkeeping/add_unit.html', {'properties': properties})

# Edit Unit
def edit_unit(request, pk):
    unit = get_object_or_404(Unit, id=pk)  # Fetch the unit using the primary key

    if request.method == 'POST':
        # Update unit details from the form data
        unit.unit_name = request.POST.get('unit_name')
        unit.floor_area = request.POST.get('floor_area')
        unit.rooms = request.POST.get('rooms')
        unit.baths = request.POST.get('baths')
        unit.market_rent = request.POST.get('market_rent')

        # Retrieve the property using the unit's property relationship
        property_id = unit.property.id  # Fetch the associated property ID
        unit.property = get_object_or_404(Property, id=property_id)

        # Save the updated unit
        unit.save()

        # Redirect to the associated property's detail view
        return redirect('property_detail', property_id=property_id)

    # Fetch all properties for the dropdown (if needed, though it's redundant in this case)
    properties = Property.objects.all()
    return render(request, 'bookkeeping/edit_unit.html', {
        'unit': unit,
        'properties': properties,
    })

# Delete Unit
def delete_unit(request, pk):
    unit = get_object_or_404(Unit, id=pk)
    property_id = unit.property.id  # Store the property ID before deletion

    if request.method == 'POST':
        unit.delete()
        # Redirect to property detail view after deleting the unit
        return redirect('property_detail', property_id=property_id)

    return render(request, 'bookkeeping/delete_unit.html', {'unit': unit})

#################################################################

# Landlords View
def landlords(request):
    query = request.GET.get('q', '')
    landlords = Landlord.objects.all()

    if query:
        landlords = landlords.filter(name__icontains=query)  # Filter landlords by name

    return render(request, 'bookkeeping/landlords.html', {
        'landlords': landlords,
    })
    
# Add Landlord
def add_landlord(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        phone_number = request.POST.get('phone_number')
        email = request.POST.get('email')
        address = request.POST.get('address')
        iban = request.POST.get('iban')
        bic = request.POST.get('bic')
        tax_id = request.POST.get('tax_id')
        company_name = request.POST.get('company_name')
        notes = request.POST.get('notes')

        # Create the landlord
        Landlord.objects.create(
            name=name,
            phone_number=phone_number,
            email=email,
            address=address,
            iban=iban,
            bic=bic,
            tax_id=tax_id,
            company_name=company_name,
            notes=notes,
        )
        return redirect('landlords')

    return render(request, 'bookkeeping/add_landlord.html')

# Edit Landlord
def edit_landlord(request, pk):
    landlord = get_object_or_404(Landlord, id=pk)

    if request.method == 'POST':
        landlord.name = request.POST.get('name')
        landlord.phone_number = request.POST.get('phone_number')
        landlord.email = request.POST.get('email')
        landlord.address = request.POST.get('address')
        landlord.iban = request.POST.get('iban')
        landlord.bic = request.POST.get('bic')
        landlord.tax_id = request.POST.get('tax_id')
        landlord.company_name = request.POST.get('company_name')
        landlord.notes = request.POST.get('notes')

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
    headers = ["Date", "Account Name", "Transaction Type", "Betrag Brutto", "Ust.", "Betrag Netto"]
    ws.append(headers)

    # Retrieve parsed transactions
    parsed_transactions = ParsedTransaction.objects.all()

    # Add data rows
    for transaction in parsed_transactions:
        ws.append([
            transaction.date.strftime("%Y-%m-%d") if transaction.date else "N/A",
            transaction.account_name or "N/A",
            transaction.transaction_type or "N/A",
            transaction.betrag_brutto if transaction.betrag_brutto is not None else "N/A",
            transaction.ust,  # Calculated UST property
            transaction.betrag_netto,  # Calculated Net Amount property
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
        start_date = request.POST.get('start_date') or None
        end_date = request.POST.get('end_date') or None
        ust_type = request.POST.get('ust_type')
        deposit_amount = request.POST.get('deposit_amount') or Decimal(0)

        # Fetch the unit and its associated property, landlords, and rent
        unit_obj = get_object_or_404(Unit, id=unit_id)
        property_obj = unit_obj.property
        landlords = property_obj.landlords.all()
        rent = unit_obj.market_rent

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

        # Redirect to property detail view
        return redirect(f"{reverse('property_detail', args=[property_obj.id])}?tab=leases")
    
    # Fetch data for dropdowns if needed
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
        lease.unit = get_object_or_404(Unit, id=request.POST.get('unit'))
        lease.tenant = get_object_or_404(Tenant, id=request.POST.get('tenant'))
        lease.start_date = request.POST.get('start_date') or None
        lease.end_date = request.POST.get('end_date') or None
        lease.ust_type = request.POST.get('ust_type')
        lease.deposit_amount = request.POST.get('deposit_amount')

        # Save updated landlords
        landlord_ids = request.POST.getlist('landlords')
        lease.landlords.set(landlord_ids)

        # Save the updated lease
        lease.save()

        # Redirect to property detail view
        return redirect(f"{reverse('property_detail', args=[lease.property.id])}?tab=leases")
    
    # Fetch data for dropdowns
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
    property_id = lease.property.id  # Store the associated property ID before deletion

    if request.method == 'POST':
        lease.delete()

        # Redirect to property detail view
        return redirect(f"{reverse('property_detail', args=[lease.property.id])}?tab=leases")

    return render(request, 'bookkeeping/delete_lease.html', {'lease': lease})

#################################################################

# Income Profiles
def income_profiles(request):
    properties = Property.objects.prefetch_related('leases__income_profiles', 'income_profiles')
    return render(request, 'bookkeeping/income_profiles.html', {'properties': properties})

# Add Income Profile
def add_income_profile(request):
    if request.method == 'POST':
        lease_id = request.POST.get('lease')
        property_id = request.POST.get('property')
        amount = request.POST.get('amount')
        date = request.POST.get('date')

        # Fetch Lease and Property
        lease = Lease.objects.filter(id=lease_id).first() if lease_id else None
        property_obj = get_object_or_404(Property, id=property_id)

        # Determine UST dynamically
        ust = 0
        if lease and lease.ust_type:
            ust = {'Voll': 19, 'Teilw': 7, 'Nicht': 0}.get(lease.ust_type, 0)

        # Safely parse optional fields
        try:
            amount = Decimal(amount) if amount else None
        except Exception:
            amount = None
        try:
            date = datetime.strptime(date, "%Y-%m-%d").date() if date else None
        except Exception:
            date = None

        # Create Income Profile
        IncomeProfile.objects.create(
            lease=lease,
            property=property_obj,
            # profile_name=request.POST.get('profile_name'),
            transaction_type=request.POST.get('transaction_type'),
            amount=amount,
            date=date,
            recurring=request.POST.get('recurring') == 'on',
            frequency=request.POST.get('frequency'),
            account_name=request.POST.get('account_name'),
            ust=ust,
            booking_no=request.POST.get('booking_no'),
        )
        return redirect(f"{reverse('property_detail', args=[property_obj.id])}?tab=income")

    return redirect('dashboard')  # Default fallback


# Edit Income Profile
def edit_income_profile(request, pk):
    income = get_object_or_404(IncomeProfile, id=pk)
    property_obj = income.property

    if request.method == 'POST':
        lease_id = request.POST.get('lease')
        property_id = request.POST.get('property')
        amount = request.POST.get('amount')
        date = request.POST.get('date')

        # Fetch Lease and Property
        lease = Lease.objects.filter(id=lease_id).first() if lease_id else None

        # Determine UST dynamically
        ust = 0
        if lease and lease.ust_type:
            ust = {'Voll': 19, 'Teilw': 7, 'Nicht': 0}.get(lease.ust_type, 0)

        # Safely parse optional fields
        try:
            income.amount = Decimal(amount) if amount else None
        except Exception:
            income.amount = None
        try:
            income.date = datetime.strptime(date, "%Y-%m-%d").date() if date else None
        except Exception:
            income.date = None

        # Update fields
        income.lease = lease
        income.property = property_obj
        # income.profile_name = request.POST.get('profile_name')
        income.transaction_type = request.POST.get('transaction_type')
        income.recurring = request.POST.get('recurring') == 'on'
        income.frequency = request.POST.get('frequency') if income.recurring else None
        income.account_name = request.POST.get('account_name')
        income.ust = ust
        income.booking_no = request.POST.get('booking_no')

        income.save()
        return redirect(f"{reverse('property_detail', args=[property_obj.id])}?tab=income")

    return redirect('dashboard')  # Default fallback


# Delete Income Profile
def delete_income_profile(request, pk):
    income_profile = get_object_or_404(IncomeProfile, id=pk)
    property_obj = income_profile.property

    if request.method == 'POST':
        income_profile.delete()
        return redirect(f"{reverse('property_detail', args=[property_obj.id])}?tab=income")

    return redirect('dashboard')  # Default fallback

#################################################################

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

#################################################################

# AJAX endpoint to fetch lease profiles
def lease_profiles(request, lease_id):
    lease = get_object_or_404(Lease, id=lease_id)
    income_profiles = IncomeProfile.objects.filter(lease=lease)
    expense_profiles = ExpenseProfile.objects.filter(lease=lease)

    return render(request, 'bookkeeping/lease.html', {
        'lease': lease,
        'income_profiles': income_profiles,
        'expense_profiles': expense_profiles,
    })

from django.db.models import Sum, Avg
from django.utils.timezone import now, timedelta

def property_detail(request, property_id):
    property_obj = get_object_or_404(Property, id=property_id)
    leases = property_obj.leases.all()
    income_profiles = IncomeProfile.objects.filter(property=property_obj)
    expense_profiles = ExpenseProfile.objects.filter(property=property_obj)
    earmarked_transactions = EarmarkedTransaction.objects.filter(property=property_obj).order_by('-date')
    parsed_transactions = ParsedTransaction.objects.filter(related_property=property_obj).order_by('-date')
    landlords = Landlord.objects.all()

    # Financial Overview
    total_revenue = income_profiles.aggregate(total=Sum('amount'))['total'] or 0
    total_expenses = expense_profiles.aggregate(total=Sum('amount'))['total'] or 0
    net_income = total_revenue - total_expenses

    # Unit Statistics
    total_units = property_obj.units.count()
    leased_units = leases.count()
    occupancy_rate = (leased_units / total_units) * 100 if total_units else 0
    avg_rent = leases.aggregate(average=Avg('rent'))['average'] or 0

    # Example: Last 6 months data
    chart_data = {
        "labels": [],  # Months or other periods
        "revenue": [],
        "expenses": []
    }

    current_date = now()
    for i in range(6):
        month = (current_date - timedelta(days=30 * i)).strftime("%B %Y")
        revenue = income_profiles.filter(date__month=(current_date - timedelta(days=30 * i)).month).aggregate(total=Sum('amount'))['total'] or 0
        expense = expense_profiles.filter(date__month=(current_date - timedelta(days=30 * i)).month).aggregate(total=Sum('amount'))['total'] or 0
        chart_data["labels"].append(month)
        chart_data["revenue"].append(revenue)
        chart_data["expenses"].append(expense)

    context = {
        'property': property_obj,
        'units': property_obj.units.all(),
        'leases': leases,
        'income_profiles': income_profiles,
        'expense_profiles': expense_profiles,
        'earmarked_transactions': earmarked_transactions,
        'parsed_transactions': parsed_transactions,
        'financial_overview': {
            'total_revenue': total_revenue,
            'total_expenses': total_expenses,
            'net_income': net_income,
        },
        'unit_stats': {
            'total_units': total_units,
            'leased_units': leased_units,
            'occupancy_rate': occupancy_rate,
            'avg_rent': avg_rent,
        },
        "chart_data": chart_data,
        'landlords': landlords,
    }

    return render(request, 'bookkeeping/property_detail.html', context)
