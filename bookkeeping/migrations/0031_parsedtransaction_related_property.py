# Generated by Django 4.0.6 on 2024-12-19 07:20

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('bookkeeping', '0030_parsedtransaction_is_income_parsedtransaction_tenant'),
    ]

    operations = [
        migrations.AddField(
            model_name='parsedtransaction',
            name='related_property',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='bookkeeping.property'),
        ),
    ]
