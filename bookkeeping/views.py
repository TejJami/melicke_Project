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
from django.db.models import Q
from itertools import chain
from operator import attrgetter
from django.contrib.auth.views import LoginView
from django.contrib.auth import authenticate
from django.contrib.sessions.models import Session
from django.utils import timezone
from django.contrib import messages
from datetime import date
from django.db.models import Sum, F, FloatField, ExpressionWrapper
from django.core.exceptions import ValidationError
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from .models import Unit, Property
from openpyxl import Workbook
from django.http import HttpResponse
from bookkeeping.utils.onedrive_utils import upload_to_onedrive

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
    earmarked = EarmarkedTransaction.objects.all().order_by('booking_no')  # ascending
    parsed = ParsedTransaction.objects.all().order_by('booking_no')        # ascending
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

# Helper function to serialize transactions for session storage
# This function converts date objects to ISO format strings for session storage.
def serialize_for_session(tx_list):
    serialized = []
    for tx in tx_list:
        tx_copy = tx.copy()
        if isinstance(tx_copy.get('date'), date):
            tx_copy['date'] = tx_copy['date'].isoformat()  # e.g. '2024-04-10'
        serialized.append(tx_copy)
    return serialized

# Upload Bank Statement 
def upload_bank_statement(request, property_id=None):
    property_obj = get_object_or_404(Property, id=property_id)

    if request.method == 'POST' and request.FILES.get('statement'):
        statement = request.FILES['statement']
        duplicate_count = 0
        earmarked_transactions = []
        current_buchungsdatum = None

        # Extract IBAN from first page
        reader = PyPDF2.PdfReader(statement)
        first_page_text = reader.pages[0].extract_text()
        iban_match = re.search(r"IBAN:\s*([A-Z0-9\s]+)", first_page_text)

        if not iban_match:
            return render(request, 'bookkeeping/upload_statement.html', {
                'property': property_obj,
                'error': "\u26a0\ufe0f IBAN konnte im PDF nicht gefunden werden.",
            })

        extracted_iban = re.sub(r"\s+", "", iban_match.group(1))[:22]
        landlord_ibans = [iban.replace(" ", "") for iban in property_obj.landlords.values_list('iban', flat=True) if iban]

        if extracted_iban not in landlord_ibans:
            messages.error(request, f"\u274c Die IBAN {extracted_iban} stimmt nicht mit den IBANs der Vermieter \u00fcberein.")
            return redirect(f"{reverse('property_detail', args=[property_id])}?tab=dashboard")

        # Booking Number Counter Setup
        latest_bn = EarmarkedTransaction.objects.filter(
            property=property_obj
        ).exclude(booking_no__isnull=True).order_by('-booking_no').first()
        base_bn = 1
        if latest_bn and latest_bn.booking_no:
            try:
                base_bn = int(re.sub(r'\D', '', latest_bn.booking_no)) + 1
            except ValueError:
                pass
        bn_counter = base_bn

        def split_pdf_into_pages(pdf_file):
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            pages = []
            for page_num in range(len(pdf_reader.pages)):
                writer = PyPDF2.PdfWriter()
                writer.add_page(pdf_reader.pages[page_num])
                stream = BytesIO()
                writer.write(stream)
                stream.seek(0)
                pages.append(stream)
            return pages

        def extract_text_with_fallback(page_stream):
            try:
                with pdfplumber.open(page_stream) as pdf:
                    return pdf.pages[0].extract_text()
            except Exception:
                page_stream.seek(0)
                with fitz.open(stream=page_stream.read(), filetype="pdf") as pdf:
                    return pdf[0].get_text("text")

        skipped_duplicates = []  # Add this at the top with other init vars

        def save_transaction(tx_data):
            nonlocal bn_counter
            if tx_data and 'amount' in tx_data:
                tx_data['description'] = " ".join(multiline_description).strip()
                exists = EarmarkedTransaction.objects.filter(
                    date=tx_data['date'],
                    account_name=tx_data['account_name'],
                    amount=tx_data['amount'],
                    property=property_obj
                ).exists()
                if not exists:
                    txn = EarmarkedTransaction(
                        date=tx_data['date'],
                        account_name=tx_data['account_name'],
                        amount=tx_data['amount'],
                        is_income=tx_data['is_income'],
                        description=tx_data['description'],
                        property=property_obj,
                        booking_no=f"{bn_counter:04d}",
                    )
                    earmarked_transactions.append(txn)
                    bn_counter += 1
                    return True
                else:
                    skipped_duplicates.append(tx_data.copy())
            return False


        pages = split_pdf_into_pages(statement)
        for page_stream in pages:
            text = extract_text_with_fallback(page_stream)
            if not text:
                continue
            lines = text.split('\n')
            current_transaction = {}
            multiline_description = []

            for line in lines:
                line = line.strip()
                if not line:
                    continue
                if "Buchungsdatum:" in line:
                    match = re.search(r"\d{2}\.\d{2}\.\d{4}", line)
                    if match:
                        try:
                            current_buchungsdatum = match.group(0)
                            formatted_buchungsdatum = datetime.strptime(current_buchungsdatum, "%d.%m.%Y").date()
                        except ValueError:
                            formatted_buchungsdatum = None
                    continue

                if any(skip in line for skip in ["Kontostand", "Alter Kontostand", "Neuer Kontostand", "Freistellungsauftrag"]):
                    continue

                if current_buchungsdatum:
                    date_match = re.search(r"\d{2}\.\d{2}", line)
                    if date_match:
                        try:
                            parsed_date = date_match.group(0)
                            formatted_parsed_date = datetime.strptime(parsed_date, "%d.%m").date()
                            formatted_parsed_date = formatted_parsed_date.replace(year=formatted_buchungsdatum.year)
                            if formatted_parsed_date != formatted_buchungsdatum:
                                continue
                        except ValueError:
                            continue

                        save_transaction(current_transaction)

                        current_transaction = {'date': formatted_parsed_date}
                        multiline_description = []

                        current_transaction['account_name'] = line.split(parsed_date)[0].strip()
                        for col in re.split(r'\s{2,}', line):
                            amount_match = re.search(r"-?\d{1,3}(?:\.\d{3})*,\d{2}-?", col)
                            if amount_match:
                                amt = amount_match.group(0).replace('.', '').replace(',', '.')
                                current_transaction['amount'] = abs(float(amt.strip('-')))
                                current_transaction['is_income'] = not col.strip().endswith('-')
                                break
                    elif current_transaction:
                        multiline_description.append(line)

            save_transaction(current_transaction)
            print(f"Processed page {page_stream}: {len(earmarked_transactions)} transactions found.")

        if duplicate_count > 0:
            messages.warning(request, "Einige Transaktionen wurden möglicherweise übersprungen, weil sie bereits vorhanden sind.")

        for txn in earmarked_transactions:
            txn.save()


        request.session['skipped_duplicates'] = serialize_for_session(skipped_duplicates)

        return redirect(f"{reverse('property_detail', args=[property_id])}?tab=dashboard")

#################################################################

# All views for Properties
# Property List View
@login_required
def properties(request):
    query = request.GET.get('q', '')
    
    if query:
        properties = Property.objects.filter(name__icontains=query).order_by('-id')
    else:
        properties = Property.objects.all().order_by('-id')  # Newest first by ID
    
    paginator = Paginator(properties, 6)
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
        # partial_tax_rate = request.POST.get('partial_tax_rate')
        image = request.FILES.get('image')


        auto_calculate_tax = request.POST.get('auto_calculate_tax') == "on"  # Checkbox returns "on" if checked
        
        tax_calculation_method = request.POST.get('tax_calculation_method', 'none')  # Default to manual entry
        
        partial_tax_rate_input = request.POST.get('partial_tax_rate', '0').replace(',', '.')
        partial_tax_rate = float(partial_tax_rate_input) if not auto_calculate_tax else 0.0

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

# Edit Property
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

# All views for Tenants
# Tenant List View
@login_required
def tenants(request):
    query = request.GET.get('q', '')
    property_id = request.GET.get('property')

    tenants = Tenant.objects.all()

    if query:
        tenants = tenants.filter(name__icontains=query)

    if property_id:
        tenants = tenants.filter(leases__property_id=property_id).distinct()

    # Annotate each tenant with total monthly debt (rent + additional costs)
    tenants = tenants.annotate(
        total_monthly_debt=Sum(
            ExpressionWrapper(
                F('leases__rent') + F('leases__additional_costs'),
                output_field=FloatField()
            )
        )
    )

    properties = Property.objects.all()

    return render(request, 'bookkeeping/tenants.html', {
        'tenants': tenants,
        'properties': properties,
        'selected_property_id': property_id,
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

@login_required
def mapping_rules(request, property_id):
    property_obj = get_object_or_404(Property, id=property_id)

    expense_profiles = ExpenseProfile.objects.filter(property=property_obj)
    income_profiles = IncomeProfile.objects.filter(property=property_obj)

    # Merge and sort by ID (or `date` if added later)
    merged_profiles = sorted(
        chain(expense_profiles, income_profiles),
        key=attrgetter('id')  # Or use 'date' if consistent
    )

    return render(request, 'bookkeeping/mapping_rules.html', {
        'property': property_obj,
        'profiles': merged_profiles
    })

#################################################################

# Expense Profiles
def expense_profiles(request):
    properties = Property.objects.prefetch_related('leases', 'expense_profiles').all()
    return render(request, 'bookkeeping/expense_profiles.html', {
        'properties': properties,
    })

# Add Expense Profile
# def add_expense_profile(request):
#     if request.method == 'POST':
#         data = request.POST
#         invoice_file = request.FILES.get('invoice')  # Get uploaded file
        

#         # Validate Property ID
#         property_id = data.get('property')
#         if not property_id:
#             return redirect('dashboard')  # Redirect if property is missing

#         property_obj = get_object_or_404(Property, id=property_id)

#         # Fetch Lease if provided
#         lease_id = data.get('lease')
#         lease = Lease.objects.filter(id=lease_id).first() if lease_id else None

#         # Safely parse optional fields
#         amount = safe_decimal(data.get('amount'))
#         date = safe_date(data.get('date'))

#         # Validate mandatory fields
#         if not data.get('transaction_type') or not data.get('account_name'):
#             return redirect(f"{reverse('property_detail', args=[property_obj.id])}?tab=mapping_tab")

#         try:
#             # Create Expense Profile
#             ExpenseProfile.objects.create(
#                 lease=lease,
#                 property=property_obj,
#                 transaction_type=data.get('transaction_type'),
#                 account_name=data.get('account_name'),
#                 # booking_no=data.get('booking_no'),
#                 amount=amount,
#                 date=date,
#                 recurring=data.get('recurring') == 'on',
#                 frequency=data.get('frequency'),
#                 ust=data.get('ust'),
#                 invoice=invoice_file  # Attach invoice if provided
#             )
#         except ValidationError as e:
#             print(f"Validation Error: {e}")  # Log error
#             return redirect('dashboard')  # Redirect on error

#         return redirect(f"{reverse('property_detail', args=[property_obj.id])}?tab=mapping_tab")

#     return redirect('dashboard')  # Default fallback

def add_expense_profile(request):
    if request.method == 'POST':
        data = request.POST
        invoice_file = request.FILES.get('invoice')  # Uploaded file object
        invoice_url = None

        # Validate Property
        property_id = data.get('property')
        if not property_id:
            return redirect('dashboard')

        property_obj = get_object_or_404(Property, id=property_id)

        # Optional Lease
        lease_id = data.get('lease')
        lease = Lease.objects.filter(id=lease_id).first() if lease_id else None

        # Safe parsing
        amount = safe_decimal(data.get('amount'))
        date = safe_date(data.get('date'))
        recurring = data.get('recurring') == 'on'
        frequency = data.get('frequency')
        ust = int(data.get('ust') or 19)

        # Required fields
        if not data.get('transaction_type') or not data.get('account_name'):
            return redirect(f"{reverse('property_detail', args=[property_obj.id])}?tab=mapping_tab")

        # Upload invoice to OneDrive (if provided)
        if invoice_file:
            try:
                invoice_url = upload_to_onedrive(invoice_file, invoice_file.name)
            except Exception as e:
                print(f"OneDrive upload failed: {e}")

        try:
            # Create the Expense Profile
            ExpenseProfile.objects.create(
                lease=lease,
                property=property_obj,
                transaction_type=data.get('transaction_type'),
                account_name=data.get('account_name'),
                amount=amount,
                date=date,
                recurring=recurring,
                frequency=frequency,
                ust=ust,
                invoice=invoice_url  # Store the OneDrive URL
            )
        except ValidationError as e:
            print(f"Validation Error: {e}")

        return redirect(f"{reverse('property_detail', args=[property_obj.id])}?tab=mapping_tab")

    return redirect('dashboard')  # fallback

# Edit Expense Profile
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
        # expense.booking_no = data.get('booking_no')
        
        # Safely parse optional fields
        expense.amount = safe_decimal(amount)
        expense.date = safe_date(date)

        expense.save()
        return redirect(f"{reverse('property_detail', args=[property_obj.id])}?tab=mapping_tab")

    return redirect('dashboard')  # Default fallback

# Helper function to determine UST based on lease or property
def get_ust_from_lease_or_property(lease, property_obj):
    """
    Determines UST based on lease if available, otherwise defaults to the property UST.
    """
    ust_mapping = {'Voll': 19, 'Teilw': 7, 'Nicht': 0}
    if lease and lease.ust_type:
        return ust_mapping.get(lease.ust_type, 0)
    return ust_mapping.get(property_obj.ust_type, 0)

# Helper function to safely convert values to Decimal and date
def safe_decimal(value):
    """
    Safely converts a value to Decimal. Returns None if conversion fails.
    """
    try:
        return Decimal(value) if value else None
    except (ValueError, TypeError, Decimal.InvalidOperation):
        return None

# Helper function to safely parse date strings
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
        return redirect(f"{reverse('property_detail', args=[property_obj.id])}?tab=mapping_tab")

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
    property_id = request.GET.get('property')

    landlords = Landlord.objects.prefetch_related('owned_properties').all()

    if query:
        landlords = landlords.filter(name__icontains=query)

    if property_id:
        landlords = landlords.filter(owned_properties__id=property_id).distinct()

    properties = Property.objects.all()

    return render(request, 'bookkeeping/landlords.html', {
        'landlords': landlords,
        'properties': properties,
        'selected_property_id': property_id,
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

# Export parsed transactions to Excel

from openpyxl import Workbook
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.styles import numbers
from django.http import HttpResponse
from django.utils.timezone import now
from django.utils.text import slugify

def export_parsed_transactions(request, property_id):
    import calendar
    # German month names
    german_months = [
        "", "Januar", "Februar", "März", "April", "Mai", "Juni",
        "Juli", "August", "September", "Oktober", "November", "Dezember"
    ]

    # Get property
    property_obj = Property.objects.get(id=property_id)

    # Filter transactions by property
    parsed_transactions = ParsedTransaction.objects.filter(related_property=property_obj)

    # Create workbook and worksheet
    wb = Workbook()
    ws = wb.active
    ws.title = "Parsed Transactions"

    # Header row
    headers = [
        "BN", "Datum", "Kontoname", "Einheit",
        "Bank", "Nettobetrag", "Betrag Aufw", "USt (%)", "USt",
        "Bruttobetrag", "Gggkto", "Mieter", "Rechnung",
        "Monat", "L-Monat", "Objekt"
    ]
    ws.append(headers)

    # Append data rows
    for tx in parsed_transactions:
        month_int = tx.date.month if tx.date else None
        month_name = german_months[month_int] if month_int else "N/A"

        ws.append([
            tx.booking_no or "N/A",
            tx.date.strftime("%Y-%m-%d") if tx.date else "N/A",
            tx.account_name or "N/A",
            tx.unit_name or "N/A",

            tx.betrag_brutto if tx.betrag_brutto is not None else None,  # Bank
            tx.betrag_netto if tx.betrag_netto is not None else None,    # Nettobetrag
            tx.betrag_netto if tx.betrag_netto is not None else None,    # Betrag Aufw

            f"{tx.ust_type}%" if tx.ust_type is not None else "N/A",     # USt %
            tx.ust if tx.ust is not None else None,                      # USt

            tx.betrag_brutto if tx.betrag_brutto is not None else None,  # Bruttobetrag
            tx.transaction_type or "N/A",     # Gggkto
            tx.tenant or "N/A",               # Mieter
            tx.invoice.name if tx.invoice else "-",

            month_int or "N/A",
            month_name,
            property_obj.name
        ])

    # Format numeric cells (2 decimals) for appropriate columns
    for row in ws.iter_rows(min_row=2, min_col=5, max_col=10):  # Bank to Bruttobetrag
        for cell in row:
            if isinstance(cell.value, (float, int)):
                cell.number_format = numbers.FORMAT_NUMBER_00

    # Define Excel table
    num_rows = ws.max_row
    num_cols = ws.max_column

    # Handle multi-letter column names
    def col_letter(n):
        result = ""
        while n:
            n, rem = divmod(n - 1, 26)
            result = chr(65 + rem) + result
        return result

    last_col_letter = col_letter(num_cols)
    table_ref = f"A1:{last_col_letter}{num_rows}"

    table = Table(displayName="ParsedTransactionsTable", ref=table_ref)
    style = TableStyleInfo(
        name="TableStyleLight1",
        showFirstColumn=False,
        showLastColumn=False,
        showRowStripes=True,
        showColumnStripes=False
    )
    table.tableStyleInfo = style
    ws.add_table(table)

    # Auto-fit column widths
    for column_cells in ws.columns:
        max_length = 0
        column_letter = column_cells[0].column_letter
        for cell in column_cells:
            try:
                cell_value = str(cell.value) if cell.value is not None else ""
                max_length = max(max_length, len(cell_value))
            except:
                pass
        ws.column_dimensions[column_letter].width = max_length + 2  # Add padding

    # Format filename
    today = now().strftime("%Y-%m-%d")
    property_name_slug = slugify(property_obj.name)
    filename = f"FiBu_{property_name_slug}_{today}.xlsx"

    # Return response
    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
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
        date = request.POST.get('date')
        ust = int(request.POST.get('ust', 0))
        recurring = request.POST.get('recurring') == 'on'
        frequency = request.POST.get('frequency')
        account_name = request.POST.get('account_name')

        lease = get_object_or_404(Lease, id=lease_id)
        property_obj = get_object_or_404(Property, id=property_id)

        try:
            date = datetime.strptime(date, "%Y-%m-%d").date() if date else None
        except Exception:
            date = None

        try:
            total_amount = Decimal(request.POST.get('amount', '0'))
        except Exception:
            total_amount = Decimal("0.00")

        split_enabled = request.POST.get("split_income") == "on"
        apply_remainder = request.POST.get("apply_remainder") == "on"

        if split_enabled:
            selected_types = request.POST.getlist("split_types[]")
            split_total = Decimal("0.00")
            split_map = {}

            for tx_type in selected_types:
                field_key = f"split_amount_{tx_type}"
                try:
                    split_amount = Decimal(request.POST.get(field_key, "0"))
                except Exception:
                    split_amount = Decimal("0.00")

                if split_amount > 0:
                    split_map[tx_type] = float(split_amount)  # Store as float for JSON serializability
                    split_total += split_amount

            remainder = total_amount - split_total

            IncomeProfile.objects.create(
                lease=lease,
                property=property_obj,
                transaction_type=None,  # Since this is a split, no single type applies
                amount=total_amount,
                date=date,
                recurring=recurring,
                frequency=frequency,
                account_name=account_name,
                ust=ust,
                split_details=split_map
            )

            if remainder > 0 and apply_remainder:
                messages.info(request, f"Restbetrag von €{remainder:.2f} wurde nicht zugewiesen.")

        else:
            # Standard single entry
            IncomeProfile.objects.create(
                lease=lease,
                property=property_obj,
                transaction_type=request.POST.get('transaction_type'),
                amount=total_amount,
                date=date,
                recurring=recurring,
                frequency=frequency,
                account_name=account_name,
                ust=ust,
                split_details=None  # Not a split
            )

        return redirect(f"{reverse('property_detail', args=[property_obj.id])}?tab=mapping_tab")

    return redirect('dashboard')


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
        # income.booking_no = request.POST.get('booking_no')

        income.save()
        return redirect(f"{reverse('property_detail', args=[property_obj.id])}?tab=mapping_tab")

    return redirect('dashboard')  # Default fallback


# Delete Income Profile
def delete_income_profile(request, pk):
    income_profile = get_object_or_404(IncomeProfile, id=pk)
    property_obj = income_profile.property

    if request.method == 'POST':
        income_profile.delete()
        return redirect(f"{reverse('property_detail', args=[property_obj.id])}?tab=mapping_tab")

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
from django.http import JsonResponse

from django.http import JsonResponse
from decimal import Decimal

def lease_profiles(request, lease_id):
    lease = get_object_or_404(Lease, id=lease_id)

    income_data = []

    # Rent
    if lease.rent:
        income_data.append({
            "type": "rent",
            "label": "Miete",
            "amount": float(lease.rent)
        })

    # BK / Additional Costs
    additional = lease.additional_costs or (lease.unit.additional_costs if lease.unit else Decimal("0.00"))
    if additional:
        income_data.append({
            "type": "bk_advance_payments",
            "label": "Nebenkosten",
            "amount": float(additional)
        })

    # Deposit
    if lease.deposit_amount:
        income_data.append({
            "type": "security_deposit",
            "label": "Kaution",
            "amount": float(lease.deposit_amount)
        })

    return JsonResponse({
        "lease_id": lease.id,
        "incomes": income_data
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
    #sort earmarked transaction by booking no
    earmarked_transactions = EarmarkedTransaction.objects.filter(property=property_obj).order_by('booking_no')
    #Sort parsed transactions by booking no
    parsed_transactions = ParsedTransaction.objects.filter(related_property=property_obj).order_by('booking_no')
    # Combine and sort all mapping rules by creation order (fallback to ID if needed)
    all_mapping_profiles = sorted(
        chain(income_profiles, expense_profiles),
        key=attrgetter('id')  # Use `date` if available later
    )
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

    skipped_duplicates = request.session.pop('skipped_duplicates', None)

    context = {
        'property': property_obj,
        'units': property_obj.units.all(),
        'leases': leases,
        'income_profiles': income_profiles,
        'expense_profiles': expense_profiles,
        'profiles': all_mapping_profiles,
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
        'skipped_duplicates': skipped_duplicates,
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