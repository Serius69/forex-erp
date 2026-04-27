"""
Migration 0011 — Add company FK to Customer; make document_number unique per company.
"""
import django.db.models.deletion
from django.db import migrations, models


def assign_customer_company(apps, schema_editor):
    """Set company on all Customers via their transactions → branch → company."""
    Customer    = apps.get_model('transactions', 'Customer')
    Transaction = apps.get_model('transactions', 'Transaction')
    Company     = apps.get_model('tenants',      'Company')

    default_company = Company.objects.order_by('id').first()

    for customer in Customer.objects.filter(company__isnull=True):
        tx = Transaction.objects.filter(customer=customer).first()
        company_id = None
        if tx and tx.branch_id:
            Branch = apps.get_model('users', 'Branch')
            branch = Branch.objects.filter(id=tx.branch_id).first()
            if branch:
                company_id = branch.company_id

        if not company_id and default_company:
            company_id = default_company.id

        if company_id:
            customer.company_id = company_id
            customer.save(update_fields=['company'])


def reverse_customer_company(apps, schema_editor):
    Customer = apps.get_model('transactions', 'Customer')
    Customer.objects.update(company=None)


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0010_convert_amounts_to_integer'),
        ('users',        '0006_add_company_to_branch_user'),
        ('tenants',      '0001_initial'),
    ]

    operations = [
        # 1. Remove old global uniqueness on document_number
        migrations.AlterField(
            model_name='customer',
            name='document_number',
            field=models.CharField(db_index=True, max_length=50),
        ),
        # 2. Add nullable company FK
        migrations.AddField(
            model_name='customer',
            name='company',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='customers',
                to='tenants.company',
            ),
        ),
        # 3. Data migration
        migrations.RunPython(assign_customer_company, reverse_customer_company),
        # 4. Add per-company unique constraint
        migrations.AlterUniqueTogether(
            name='customer',
            unique_together={('company', 'document_number')},
        ),
        # 5. Add indexes
        migrations.AddIndex(
            model_name='customer',
            index=models.Index(
                fields=['company', 'document_number'],
                name='tx_customer_company_doc_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='customer',
            index=models.Index(
                fields=['company', 'full_name'],
                name='tx_customer_company_name_idx',
            ),
        ),
    ]
