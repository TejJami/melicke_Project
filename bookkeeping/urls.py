from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('properties/', views.properties, name='properties'),
    path('tenants/', views.tenants, name='tenants'),
    path('expenses/', views.expenses, name='expenses'),
    path('upload_statement/', views.upload_bank_statement, name='upload_statement'),
    path('add_property/', views.add_property, name='add_property'),
    path('add_tenant/', views.add_tenant, name='add_tenant'),
    path('add_expense_profile/', views.add_expense_profile, name='add_expense_profile'),
    path('edit-expense-profile/', views.edit_expense_profile, name='edit_expense_profile'),
    path('delete-expense-profile/<int:pk>/', views.delete_expense_profile, name='delete_expense_profile'),
    path('edit_property/', views.edit_property, name='edit_property'),
    path('delete_property/<int:pk>/', views.delete_property, name='delete_property'),
    path('export_parsed_transactions/', views.export_parsed_transactions, name='export_parsed_transactions'),
]
