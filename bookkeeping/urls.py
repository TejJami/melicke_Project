from django.urls import path
from . import views
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views
from django.contrib import admin  # Ensure this is imported at the top

urlpatterns = [

     # Landing Page
    path('', views.properties, name='properties'),  # Default landing page

    path('login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),

    # Property Detail Page
    path('property/<int:property_id>/', views.property_detail, name='property_detail'),

    # Units, Leases, Income, Expense already exist - no need to change those URLs
    # Add functionality for Uploading bank statement for a specific property
    path('property/<int:property_id>/upload_statement/', views.upload_bank_statement, name='upload_bank_statement'),

    # Dashboard
    path('dashboard/', views.dashboard, name='dashboard'),

    # Properties
    path('properties/', views.properties, name='properties'),
    path('add_property/', views.add_property, name='add_property'),
    path('edit_property/<int:pk>/', views.edit_property, name='edit_property'),
    path('delete_property/<int:pk>/', views.delete_property, name='delete_property'),

    # Units
    path('units/', views.units, name='units'),
    path('add_unit/', views.add_unit, name='add_unit'),
    path('edit_unit/<int:pk>/', views.edit_unit, name='edit_unit'),
    path('delete_unit/<int:pk>/', views.delete_unit, name='delete_unit'),

    # Landlords
    path('landlords/', views.landlords, name='landlords'),
    path('add_landlord/', views.add_landlord, name='add_landlord'),
    path('edit_landlord/<int:pk>/', views.edit_landlord, name='edit_landlord'),
    path('delete_landlord/<int:pk>/', views.delete_landlord, name='delete_landlord'),

    # Tenants
    path('tenants/', views.tenants, name='tenants'),
    path('add_tenant/', views.add_tenant, name='add_tenant'),
    path('edit_tenant/<int:pk>/', views.edit_tenant, name='edit_tenant'),
    path('delete_tenant/<int:pk>/', views.delete_tenant, name='delete_tenant'),
    
    # Expense Profiles
    path('expense_profiles/', views.expense_profiles, name='expense_profiles'),
    path('add_expense_profile/', views.add_expense_profile, name='add_expense_profile'),
    path('edit_expense_profile/<int:pk>/', views.edit_expense_profile, name='edit_expense_profile'),
    path('delete_expense_profile/<int:pk>/', views.delete_expense_profile, name='delete_expense_profile'),

    # Income Profiles
    path('income_profiles/', views.income_profiles, name='income_profiles'),
    path('add_income_profile/', views.add_income_profile, name='add_income_profile'),
    path('edit_income_profile/<int:pk>/', views.edit_income_profile, name='edit_income_profile'),
    path('delete_income_profile/<int:pk>/', views.delete_income_profile, name='delete_income_profile'),

    # Leases
    path('leases/', views.leases, name='leases'),
    path('add_lease/', views.add_lease, name='add_lease'),
    path('edit_lease/<int:pk>/', views.edit_lease, name='edit_lease'),
    path('delete_lease/<int:pk>/', views.delete_lease, name='delete_lease'),
    path('lease_profiles/<int:lease_id>/', views.lease_profiles, name='lease_profiles'),

    # Transactions
    path('upload_statement/', views.upload_bank_statement, name='upload_statement'),
    path('export_parsed_transactions/', views.export_parsed_transactions, name='export_parsed_transactions'),


    path('property/<int:property_id>/ust/', views.ust_view, name='ust'),


    # Fetch unit tenant data
    path('fetch_unit_tenant_data/', views.fetch_unit_tenant_data, name='fetch_unit_tenant_data'),
    
    # OAuth Authentication Endpoints
    path('commerzbank/authorize/<int:property_id>/', views.authorize_commerzbank, name='authorize_commerzbank'),
    path('commerzbank/callback/', views.commerzbank_callback, name='commerzbank_callback'),

    # Fetch Transactions Separately
    path('commerzbank/get_transactions/', views.get_commerzbank_transactions, name='get_commerzbank_transactions'),
    
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
