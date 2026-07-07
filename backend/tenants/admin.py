from django.contrib import admin
from .models import Company, Subscription


class SubscriptionInline(admin.StackedInline):
    model = Subscription
    can_delete = False
    extra = 0


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display  = ['name', 'slug', 'country', 'base_currency', 'is_active', 'created_at']
    list_filter   = ['country', 'is_active']
    search_fields = ['name', 'slug', 'tax_id']
    prepopulated_fields = {'slug': ('name',)}
    inlines = [SubscriptionInline]


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ['company', 'plan', 'is_active', 'max_branches', 'max_users', 'next_billing_date']
    list_filter  = ['plan', 'is_active']
