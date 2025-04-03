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
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden

from django.contrib.auth.views import LoginView
from django.contrib.auth import authenticate
from django.contrib.sessions.models import Session
from django.utils import timezone
from django.contrib import messages

class CustomLoginView(LoginView):
    template_name = 'login.html'

    def form_valid(self, form):
        user = form.get_user()
        request = self.request
        force_login = request.POST.get("force_login") == "1"

        existing_sessions = Session.objects.filter(expire_date__gte=timezone.now())
        user_has_session = False

        for session in existing_sessions:
            data = session.get_decoded()
            if data.get('_auth_user_id') == str(user.id):
                if not force_login:
                    user_has_session = True
                    break
                else:
                    session.delete()

        if user_has_session:
            form.add_error(None, "already_logged_in")  # key only, used in template
            return self.form_invalid(form)

        return super().form_valid(form)

# Dashboard: Displays Earmarked and Parsed Transactions
@login_required
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
        duplicate_count = 0

        # Check if the file is a PDF
        statement = request.FILES['statement']
        from PyPDF2 import PdfReader

        # Get all landlord IBANs for this property
        property_landlord_ibans = list(property_obj.landlords.values_list('iban', flat=True))

        # Read the first page of the uploaded PDF to extract IBAN
        reader = PdfReader(statement)
        first_page_text = reader.pages[0].extract_text()
        iban_match = re.search(r"IBAN:\s*([A-Z0-9\s]+)", first_page_text)

        if not iban_match:
            return render(request, 'bookkeeping/upload_statement.html', {
                'property': property_obj,
                'error': "⚠️ IBAN konnte im PDF nicht gefunden werden.",
            })

        extracted_iban = re.sub(r"\s+", "", iban_match.group(1))[:22] # Normalize format

        # Normalize property landlord IBANs
        normalized_ibans = [iban.replace(" ", "") for iban in property_landlord_ibans if iban]
        print(f"Extracted IBAN: {extracted_iban}")
        print(f"Normalized IBANs: {normalized_ibans}")

        # Check if extracted IBAN matches any of the property's landlord IBANs
        if extracted_iban not in normalized_ibans:
            from django.contrib import messages

            messages.error(request, f"❌ Die IBAN {extracted_iban} stimmt nicht mit den IBANs der Vermieter überein.")
            return redirect(f"{reverse('property_detail', args=[property_id])}?tab=dashboard")

        # Now continue with earmarked transaction parsing...
            
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
                    # Check for duplicates (fast lookup by date, account name, and amount only)
                    exists = EarmarkedTransaction.objects.filter(
                        date=current_transaction['date'],
                        account_name=current_transaction['account_name'],
                        amount=current_transaction['amount']
                    ).exists()

                    if not exists:
                        txn = EarmarkedTransaction(
                            date=current_transaction['date'],
                            account_name=current_transaction['account_name'],
                            amount=current_transaction['amount'],
                            is_income=current_transaction['is_income'],
                            description=current_transaction['description'],
                            property=property_obj,
                        )
                        earmarked_transactions.append(txn)
                    else:
                        duplicate_count += 1
                except Exception as e:
                    print(f"Error saving last transaction on page {page_number + 1}: {e}")
        
        if duplicate_count > 0:
            from django.contrib import messages
            # Display a warning message for skipped transactions
            messages.warning(
                request, 
                f"Einige Transaktionen wurden möglicherweise übersprungen, weil sie bereits vorhanden sind."

            )
            
        # Save all transactions to the database
        for txn in earmarked_transactions:
            txn.save()  # This will trigger the `post_save` signal

        # Redirect to the property detail view with the dashboard tab
        return redirect(f"{reverse('property_detail', args=[property_id])}?tab=dashboard")

    return render(request, 'bookkeeping/upload_statement.html', {'property': property_obj})

#################################################################

# Properties
@login_required
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
        # partial_tax_rate = request.POST.get('partial_tax_rate')
        image = request.FILES.get('image')


        auto_calculate_tax = request.POST.get('auto_calculate_tax') == "on"  # Checkbox returns "on" if checked
        print(auto_calculate_tax)
        tax_calculation_method = request.POST.get('tax_calculation_method', 'none')  # Default to manual entry
        
        partial_tax_rate_input = request.POST.get('partial_tax_rate', '0').replace(',', '.')
        partial_tax_rate = float(partial_tax_rate_input) if not auto_calculate_tax else None

        # Auto-calculation logic
        if auto_calculate_tax:
            if tax_calculation_method == 'sq_meterage':
                leases = Lease.objects.filter(property__id=property_obj.id)
                area_with_ust = sum(lease.unit.floor_area for lease in leases if lease.ust_type == 'Mit' and lease.unit.floor_area)
                total_area = sum(lease.unit.floor_area for lease in leases if lease.unit.floor_area)
                partial_tax_rate = round((area_with_ust / total_area) * 100, 2) if total_area > 0 else 0.0

            elif tax_calculation_method == 'income':
                leases = Lease.objects.filter(property__id=property_obj.id)
                income_with_ust = sum(
                    (lease.rent + (lease.additional_costs or 0) + lease.deposit_amount)
                    for lease in leases if lease.ust_type == 'Mit'
                )
                total_income = sum(
                    (lease.rent + (lease.additional_costs or 0) + lease.deposit_amount)
                    for lease in leases
                )
                partial_tax_rate = round((income_with_ust / total_income) * 100, 2) if total_income > 0 else 0.0

        # Create the Property object
        property_obj = Property.objects.create(
            property_type=property_type,
            name=name,
            street=street,
            building_no=building_no,
            city=city,
            zip=zip_code,
            country=country,
            partial_tax_rate=partial_tax_rate,
            auto_calculate_tax=auto_calculate_tax,
            tax_calculation_method=tax_calculation_method,
            image=image,
        )

        property_obj.landlords.set(landlord_ids)  # Assign landlords

        return redirect('properties')

    landlords = Landlord.objects.all()
    return render(request, 'bookkeeping/add_property.html', {
        'landlords': landlords,
    })

def edit_property(request, pk):
    property_obj = get_object_or_404(Property, id=pk)

    if request.method == 'POST':
        # Update property fields
        property_obj.property_type = request.POST.get('property_type')
        property_obj.name = request.POST.get('name')
        property_obj.street = request.POST.get('street')
        property_obj.building_no = request.POST.get('building_no')
        property_obj.city = request.POST.get('city')
        property_obj.zip = request.POST.get('zip')
        property_obj.country = request.POST.get('country')

        # Convert German-formatted numbers
        auto_calculate_tax = request.POST.get('auto_calculate_tax') == "on"
        print('auto',auto_calculate_tax)
        tax_calculation_method = request.POST.get('tax_calculation_method', 'none')
        print('method',tax_calculation_method)

        partial_tax_rate_input = request.POST.get('partial_tax_rate', '0').replace(',', '.')
        partial_tax_rate = float(partial_tax_rate_input) if not auto_calculate_tax else None

        # Auto-calculation logic
        if auto_calculate_tax:
            if tax_calculation_method == 'sq_meterage':
                leases = Lease.objects.filter(property=property_obj)
                area_with_ust = sum(lease.unit.floor_area for lease in leases if lease.ust_type == 'Mit' and lease.unit.floor_area)
                total_area = sum(lease.unit.floor_area for lease in leases if lease.unit.floor_area)
                partial_tax_rate = round((area_with_ust / total_area) * 100, 2) if total_area > 0 else 0.0

            elif tax_calculation_method == 'income':
                leases = Lease.objects.filter(property=property_obj)
                income_with_ust = sum(
                    (lease.rent + (lease.additional_costs or 0) + lease.deposit_amount)
                    for lease in leases if lease.ust_type == 'Mit'
                )
                total_income = sum(
                    (lease.rent + (lease.additional_costs or 0) + lease.deposit_amount)
                    for lease in leases
                )
                partial_tax_rate = round((income_with_ust / total_income) * 100, 2) if total_income > 0 else 0.0


        property_obj.auto_calculate_tax = auto_calculate_tax
        property_obj.tax_calculation_method = tax_calculation_method
        property_obj.partial_tax_rate = partial_tax_rate

        # Update landlords
        landlord_ids = request.POST.getlist('landlords')
        property_obj.landlords.set(landlord_ids)

        # Save and release lock
        property_obj.locked_by = None  # FIXED: was `property.locked_by`
        property_obj.save()

        return redirect('property_detail', property_id=pk)

    landlords = Landlord.objects.all()
    return render(request, 'bookkeeping/edit_property.html', {
        'property': property_obj,
        'landlords': landlords,
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
@login_required
def tenants(request):
    query = request.GET.get('q', '')
    tenants = Tenant.objects.all()

    if query:
        tenants = tenants.filter(name__icontains=query)  # Filter tenants by name

    return render(request, 'bookkeeping/tenants.html', {
        'tenants': tenants,
    })

# Add Tenant
@login_required
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

from django.core.exceptions import ValidationError

def add_expense_profile(request):
    if request.method == 'POST':
        data = request.POST
        invoice_file = request.FILES.get('invoice')  # Get uploaded file
        print(invoice_file)

        # Validate Property ID
        property_id = data.get('property')
        if not property_id:
            return redirect('dashboard')  # Redirect if property is missing

        property_obj = get_object_or_404(Property, id=property_id)

        # Fetch Lease if provided
        lease_id = data.get('lease')
        lease = Lease.objects.filter(id=lease_id).first() if lease_id else None

        # Safely parse optional fields
        amount = safe_decimal(data.get('amount'))
        date = safe_date(data.get('date'))

        # Validate mandatory fields
        if not data.get('transaction_type') or not data.get('account_name'):
            return redirect(f"{reverse('property_detail', args=[property_obj.id])}?tab=expense")

        try:
            # Create Expense Profile
            ExpenseProfile.objects.create(
                lease=lease,
                property=property_obj,
                transaction_type=data.get('transaction_type'),
                account_name=data.get('account_name'),
                booking_no=data.get('booking_no'),
                amount=amount,
                date=date,
                recurring=data.get('recurring') == 'on',
                frequency=data.get('frequency'),
                ust=data.get('ust'),
                invoice=invoice_file  # Attach invoice if provided
            )
        except ValidationError as e:
            print(f"Validation Error: {e}")  # Log error
            return redirect('dashboard')  # Redirect on error

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
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from .models import Unit, Property

def add_unit(request):
    if request.method == 'POST':
        property_id = request.POST.get('property')
        unit_name = request.POST.get('unit_name')
        floor_area = request.POST.get('floor_area')
        rent = request.POST.get('rent')
        additional_costs = request.POST.get('additional_costs')
        floor = request.POST.get('floor')
        position = request.POST.get('position')

        # Ensure the property exists
        property_obj = get_object_or_404(Property, id=property_id)

        # Convert data to appropriate types
        floor_area = float(floor_area) if floor_area else None
        rent = Decimal(rent) if rent else None
        additional_costs = Decimal(additional_costs) if additional_costs else None
        floor = int(floor) if floor else None

        # Create the unit
        Unit.objects.create(
            property=property_obj,
            unit_name=unit_name,
            floor_area=floor_area,
            rent=rent,
            additional_costs=additional_costs,
            floor=floor,
            position=position
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
        unit.rent = request.POST.get('rent')
        unit.additional_costs = request.POST.get('additional_costs')
        unit.floor = request.POST.get('floor')
        unit.position = request.POST.get('position')

        # Convert data to appropriate types
        unit.floor_area = float(unit.floor_area) if unit.floor_area else None
        unit.rent = Decimal(unit.rent) if unit.rent else None
        unit.additional_costs = Decimal(unit.additional_costs) if unit.additional_costs else None
        unit.floor = int(unit.floor) if unit.floor else None

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

    # Prefetch properties using the correct reverse relation (from Property's landlords field)
    landlords = Landlord.objects.prefetch_related('owned_properties').all()


    if query:
        landlords = landlords.filter(name__icontains=query)  # Filter landlords by name

    return render(request, 'bookkeeping/landlords.html', {
        'landlords': landlords,
    })

# Add Landlord
def add_landlord(request):
    if request.method == 'POST':
        print(request.POST)
        name = request.POST.get('name')
        phone_number = request.POST.get('phone_number')
        email = request.POST.get('email')
        address = request.POST.get('address')
        iban = request.POST.get('iban')
        bic = request.POST.get('bic')
        tax_id = request.POST.get('tax_id')
        objects  = request.POST.get('object')
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
            object =objects ,
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
        landlord.object  = request.POST.get('object ')
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
        tenant_ids = request.POST.getlist('tenants')  # Get multiple tenants as a list
        start_date = request.POST.get('start_date') or None
        end_date = request.POST.get('end_date') or None
        ust_type = request.POST.get('ust_type')
        deposit_amount = request.POST.get('deposit_amount') or Decimal(0)

        # Fetch the unit and its associated property, landlords, and rent
        unit_obj = get_object_or_404(Unit, id=unit_id)
        property_obj = unit_obj.property
        landlords = property_obj.landlords.all()
        rent = unit_obj.rent

        # Fetch tenants and extract data
        tenants = Tenant.objects.filter(id__in=tenant_ids)
        account_names = [tenant.name for tenant in tenants]
        ibans = [tenant.iban for tenant in tenants]

        additional_costs = unit_obj.additional_costs  # Fetch additional costs from the unit

        lease = Lease.objects.create(
            property=property_obj,
            unit=unit_obj,
            start_date=start_date,
            end_date=end_date,
            ust_type=ust_type,
            deposit_amount=deposit_amount,
            rent=rent,
            additional_costs=additional_costs,  # Store in lease
            account_names=account_names,
            ibans=ibans,
        )

        lease.landlords.set(landlords)  # Set landlords for the lease
        lease.tenants.set(tenants)  # Assign multiple tenants
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
        lease.start_date = request.POST.get('start_date') or None
        lease.end_date = request.POST.get('end_date') or None
        lease.ust_type = request.POST.get('ust_type')

        # Convert deposit amount safely
        deposit_amount = request.POST.get('deposit_amount', '0').replace(',', '.')
        lease.deposit_amount = Decimal(deposit_amount)

        # Fetch unit's rent
        lease.rent = lease.unit.rent

        lease.additional_costs = lease.unit.additional_costs  # Update from unit

        # Save updated landlords
        landlord_ids = request.POST.getlist('landlords')
        lease.landlords.set(landlord_ids)

        # Handle multiple tenants
        tenant_ids = request.POST.getlist('tenants')
        tenants = Tenant.objects.filter(id__in=tenant_ids)
        lease.tenants.set(tenants)

        # Update account names & IBANs for tenants
        lease.account_names = [tenant.name for tenant in tenants]
        lease.ibans = [tenant.iban for tenant in tenants]

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

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from .models import Unit, Tenant

def fetch_unit_tenant_data(request):
    unit_id = request.GET.get('unit_id')
    tenant_ids = request.GET.getlist('tenant_ids[]')  # Get multiple tenant IDs

    response = {}

    if unit_id:
        unit = get_object_or_404(Unit, id=unit_id)
        response['property_id'] = unit.property.id
        response['landlord_ids'] = list(unit.property.landlords.values_list('id', flat=True))
        response['rent'] = unit.rent

    if tenant_ids:
        tenants = Tenant.objects.filter(id__in=tenant_ids)
        response['account_names'] = [tenant.name for tenant in tenants]
        response['ibans'] = [tenant.iban for tenant in tenants]

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

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from .models import Property

def get_property_locks(request):
    if request.user.is_authenticated:
        locks = Property.objects.filter(locked_by__isnull=False).values('id', 'locked_by__username')
        return JsonResponse(list(locks), safe=False)
    return JsonResponse({"error": "Unauthorized"}, status=403)


@csrf_exempt
def unlock_property(request, property_id):
    if request.method == "POST" and request.user.is_authenticated:
        try:
            prop = Property.objects.get(id=property_id)
            if prop.locked_by == request.user:
                prop.locked_by = None
                prop.save(update_fields=["locked_by"])
                print(f"[unlock_property] 🔓 Unlocked property {property_id} by {request.user.username}")
                return JsonResponse({"status": "unlocked"})
        except Property.DoesNotExist:
            pass
    return JsonResponse({"status": "error"}, status=400)

def property_detail(request, property_id):
    property_obj = get_object_or_404(Property, id=property_id)

    # FIXED: reference was to `property`, changed to `property_obj`
    locked_by_another_user = False
    if property_obj.locked_by and property_obj.locked_by != request.user:
        locked_by_another_user = True
    else:
        if property_obj.locked_by != request.user:
            property_obj.locked_by = request.user
            property_obj.save(update_fields=['locked_by'])

    # Related data
    leases = property_obj.leases.all()
    income_profiles = IncomeProfile.objects.filter(property=property_obj)
    expense_profiles = ExpenseProfile.objects.filter(property=property_obj)
    earmarked_transactions = EarmarkedTransaction.objects.filter(property=property_obj).order_by('-date')
    parsed_transactions = ParsedTransaction.objects.filter(related_property=property_obj).order_by('-date')
    landlords = Landlord.objects.all()
    tenants = Tenant.objects.all()
    property_landlords = property_obj.landlords.all()

    # Financial overview
    total_revenue = income_profiles.aggregate(total=Sum('amount'))['total'] or 0
    total_expenses = expense_profiles.aggregate(total=Sum('amount'))['total'] or 0
    net_income = total_revenue - total_expenses

    # Unit statistics
    total_units = property_obj.units.count()
    leased_units = leases.count()
    occupancy_rate = (leased_units / total_units) * 100 if total_units else 0
    avg_rent = leases.aggregate(average=Avg('rent'))['average'] or 0

    # Chart data
    chart_data = {
        "labels": [],
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
        'tenants': tenants,
        'property_landlords': property_landlords,
        'locked_by_another_user': locked_by_another_user,
    }
    print(f"[property_detail] 🔒 Property {property_obj.id} locked by {property_obj.locked_by}")
    return render(request, 'bookkeeping/property_detail.html', context)


from django.db.models import Sum, F, FloatField


def ust_view(request, property_id):
    # Get the Property object
    property_instance = get_object_or_404(Property, id=property_id)

    # Filter transactions by related_property and aggregate by month
    monthly_data = ParsedTransaction.objects.filter(related_property_id=property_id).annotate(
        month=F('date__month')  # Assuming `date` stores the transaction date
    ).values(
        'month'
    ).annotate(
        umzu19_netto=Sum(F('betrag_brutto') / (1 + F('ust_type') / 100), output_field=FloatField()),
        vorsteuer=Sum(
            (F('betrag_brutto') - (F('betrag_brutto') / (1 + F('ust_type') / 100))),
            output_field=FloatField()
        ),
        saldo_ust=Sum(
            (F('betrag_brutto') * F('ust_type') / 100) - 
            (F('betrag_brutto') - (F('betrag_brutto') / (1 + F('ust_type') / 100))),
            output_field=FloatField()
        )
    ).order_by('month')

    # Calculate totals for the summary row
    totals = monthly_data.aggregate(
        total_umzu19_netto=Sum('umzu19_netto'),
        total_vorsteuer=Sum('vorsteuer'),
        total_saldo_ust=Sum('saldo_ust')
    )

    # Add 19% calculation
    total_19_percent = totals['total_umzu19_netto'] * 0.19 if totals['total_umzu19_netto'] else 0

    # Pass data to the context
    context = {
        'property': property_instance,
        'monthly_data': monthly_data,
        'totals': totals,
        'total_19_percent': total_19_percent,
    }
    return render(request, 'bookkeeping/ust.html', context)

#################################################################

import requests
import json
from django.http import JsonResponse
from django.shortcuts import redirect
from django.conf import settings
from urllib.parse import urlencode

# Base API URL for Corporate Payments
COMMERZBANK_BASE_URL = "https://api-sandbox.commerzbank.com/corporate-payments-api/1/v1"

# OAuth2 Endpoints
AUTH_BASE_URL = "https://api-sandbox.commerzbank.com/auth/realms/sandbox/protocol/openid-connect"
AUTHORIZE_URL = f"{AUTH_BASE_URL}/auth"
TOKEN_URL = f"{AUTH_BASE_URL}/token"

def authorize_commerzbank(request, property_id):
    """Redirects user to Commerzbank OAuth2 login."""
    print(f"[authorize_commerzbank] 🔄 Redirecting for authorization (Property ID: {property_id})")

    if not settings.COMMERZBANK_CLIENT_ID or not settings.COMMERZBANK_CLIENT_SECRET:
        return JsonResponse({"error": "Missing API credentials"}, status=500)

    request.session["property_id"] = property_id  # Store property ID for later

    params = {
        "response_type": "code",
        "client_id": settings.COMMERZBANK_CLIENT_ID,
        "redirect_uri": settings.COMMERZBANK_REDIRECT_URI,
        "state": "secure_random_string"
    }

    auth_url = f"{AUTHORIZE_URL}?{requests.compat.urlencode(params)}"
    print(f"[authorize_commerzbank] 🔗 Redirecting to: {auth_url}")

    return redirect(auth_url)

def commerzbank_callback(request):
    """Handles OAuth2 callback and retrieves the access token."""
    print("[commerzbank_callback] 🔄 Handling OAuth2 callback...")

    code = request.GET.get("code")
    property_id = request.session.get("property_id")

    if not code:
        return JsonResponse({"error": "No authorization code received."}, status=400)

    if not property_id:
        return JsonResponse({"error": "Property ID missing."}, status=400)

    # Exchange authorization code for access token
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.COMMERZBANK_REDIRECT_URI,
        "client_id": settings.COMMERZBANK_CLIENT_ID,
        "client_secret": settings.COMMERZBANK_CLIENT_SECRET,
    }

    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    response = requests.post(TOKEN_URL, data=data, headers=headers)

    if response.status_code == 200:
        token_data = response.json()
        access_token = token_data.get("access_token")
        request.session["access_token"] = access_token
        print(f"[commerzbank_callback] ✅ Access Token Retrieved: {access_token[:10]}...")

        # Redirect to property page with success flag
        return redirect(f"/property/{property_id}/?auth_success=true")

    else:
        return JsonResponse({"error": "Authentication failed."}, status=400)

def fetch_commerzbank_messages(access_token):
    """Fetch available messages (only camt.053 bank statements) from Commerzbank API."""
    print("[fetch_commerzbank_messages] 🔄 Fetching bank statements (camt.053)...")

    messages_url = f"{COMMERZBANK_BASE_URL}/messages?OrderType=C53"  # Only camt.053
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    response = requests.get(messages_url, headers=headers)
    print(f"[fetch_commerzbank_messages] 🏦 API Response Status: {response.status_code}")

    if response.status_code == 200:
        try:
            messages_data = response.json()
            print(f"[fetch_commerzbank_messages] ✅ Bank Statements Retrieved: {json.dumps(messages_data, indent=2)}")
            return messages_data
        except json.JSONDecodeError:
            return {"error": "Invalid JSON response from Commerzbank API."}
    else:
        return {"error": f"Failed to retrieve messages. Status: {response.status_code}"}

import requests
from django.http import JsonResponse
from django.conf import settings

COMMERZBANK_BASE_URL = "https://api-sandbox.commerzbank.com/corporate-payments-api/1/v1/bulk-payments"

def get_commerzbank_transactions(request):
    """Fetches C53 bank statement transactions."""
    print("[get_commerzbank_transactions] 🔄 Fetching bank statements...")

    access_token = request.session.get("access_token")
    if not access_token:
        return JsonResponse({"error": "User not authenticated."}, status=401)

    # Step 1: Get the list of available C53 messages
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "ClientProduct": "Test_AppV0.1"
    }

    response = requests.get(f"{COMMERZBANK_BASE_URL}/messages?OrderType=C53", headers=headers)

    if response.status_code != 200:
        return JsonResponse({"error": "Failed to retrieve messages.", "status": response.status_code}, status=response.status_code)

    messages_data = response.json()

    # ✅ Check if response is a list
    if isinstance(messages_data, list):
        messages = messages_data  # Assign it directly
    else:
        messages = messages_data.get("messages", [])  # Fallback if API changes

    transactions = []

    # Step 2: Fetch bank statement details for each message ID
    for message in messages:
        message_id = message.get("MessageId")  # Ensure it's a dict before accessing
        if not message_id:
            continue

        statement_url = f"{COMMERZBANK_BASE_URL}/messages/{message_id}"
        statement_response = requests.get(statement_url, headers=headers)

        if statement_response.status_code == 200:
            transactions.append(statement_response.text)  # XML response (camt.053 format)
        else:
            print(f"[get_commerzbank_transactions] ❌ Failed to fetch statement {message_id}, Status: {statement_response.status_code}")

        # Step 3: Confirm retrieval
        confirm_url = f"{COMMERZBANK_BASE_URL}/messages/{message_id}"
        confirm_data = {"received": "complete"}
        confirm_response = requests.put(confirm_url, headers=headers, json=confirm_data)

        if confirm_response.status_code != 200:
            print(f"[get_commerzbank_transactions] ⚠️ Failed to confirm retrieval of {message_id}")

    return JsonResponse({"transactions": transactions})


def extract_transactions_from_camt(statement_details):
    """Extract transactions from camt.053 bank statement XML response."""
    try:
        transactions = []
        import xml.etree.ElementTree as ET

        root = ET.fromstring(statement_details)
        ns = {'ns': "urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"}

        # Iterate through each transaction
        for entry in root.findall(".//ns:Stmt/ns:Ntry", ns):
            amount = entry.find("ns:Amt", ns).text
            currency = entry.find("ns:Amt", ns).attrib.get("Ccy", "EUR")
            date = entry.find("ns:BookgDt/ns:Dt", ns).text
            description = entry.find("ns:AddtlNtryInf", ns).text

            transactions.append({
                "date": date,
                "amount": f"{amount} {currency}",
                "description": description
            })

        return transactions
    except Exception as e:
        print(f"[extract_transactions_from_camt] ❌ Error parsing camt.053: {e}")
        return []