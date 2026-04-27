"""
Migration 0006 — Multi-tenant SaaS: add Company FK to Branch and User.

Data migration strategy:
  1. Create a default Company (Kapitalya default).
  2. Assign all existing Branches to that company.
  3. Assign all existing Users to that company (via their branch.company or direct).
"""
import django.db.models.deletion
from django.db import migrations, models


def create_default_company(apps, schema_editor):
    Company      = apps.get_model('tenants', 'Company')
    Subscription = apps.get_model('tenants', 'Subscription')
    Branch       = apps.get_model('users', 'Branch')
    User         = apps.get_model('users', 'User')

    company, created = Company.objects.get_or_create(
        slug='kapitalya-default',
        defaults={
            'name':          'Kapitalya (Default)',
            'tax_id':        '',
            'country':       'BO',
            'base_currency': 'BOB',
            'is_active':     True,
        },
    )

    Subscription.objects.get_or_create(
        company=company,
        defaults={
            'plan':               'ENTERPRISE',
            'is_active':          True,
            'max_branches':       50,
            'max_users':          200,
            'max_transactions_mo': 999999,
        },
    )

    # Assign all branches to the default company
    Branch.objects.filter(company__isnull=True).update(company=company)

    # Assign all users to the default company
    User.objects.filter(company__isnull=True).update(company=company)


def reverse_default_company(apps, schema_editor):
    Company = apps.get_model('tenants', 'Company')
    Branch  = apps.get_model('users', 'Branch')
    User    = apps.get_model('users', 'User')
    Branch.objects.update(company=None)
    User.objects.update(company=None)
    Company.objects.filter(slug='kapitalya-default').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('users',   '0005_user_security_fields'),
        ('tenants', '0001_initial'),
    ]

    operations = [
        # 1. Add nullable company FK to Branch
        migrations.AddField(
            model_name='branch',
            name='company',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='branches',
                to='tenants.company',
            ),
        ),
        # 2. Add city + is_main to Branch
        migrations.AddField(
            model_name='branch',
            name='city',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='branch',
            name='is_main',
            field=models.BooleanField(default=False),
        ),
        # 3. Add nullable company FK to User
        migrations.AddField(
            model_name='user',
            name='company',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='users',
                to='tenants.company',
            ),
        ),
        # 4. Data migration — seed default company and assign existing records
        migrations.RunPython(create_default_company, reverse_default_company),
        # 5. Add indexes
        migrations.AddIndex(
            model_name='branch',
            index=models.Index(fields=['company', 'is_active'], name='users_branch_company_active_idx'),
        ),
        migrations.AddIndex(
            model_name='user',
            index=models.Index(fields=['company', 'role'], name='users_user_company_role_idx'),
        ),
    ]
