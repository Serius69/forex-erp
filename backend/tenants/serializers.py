from rest_framework import serializers
from .models import Company, Subscription


class SubscriptionSerializer(serializers.ModelSerializer):
    is_in_trial = serializers.ReadOnlyField()

    class Meta:
        model  = Subscription
        fields = [
            'plan', 'is_active', 'trial_ends', 'is_in_trial',
            'max_branches', 'max_users', 'max_transactions_mo',
            'billing_email', 'next_billing_date',
        ]
        read_only_fields = ['is_in_trial']


class CompanySerializer(serializers.ModelSerializer):
    subscription = SubscriptionSerializer(read_only=True)

    class Meta:
        model  = Company
        fields = [
            'id', 'name', 'slug', 'tax_id', 'country',
            'base_currency', 'logo_url', 'is_active',
            'created_at', 'subscription',
        ]
        read_only_fields = ['id', 'created_at']


class CompanyPublicSerializer(serializers.ModelSerializer):
    """Minimal company info embedded in auth responses."""
    class Meta:
        model  = Company
        fields = ['id', 'name', 'slug', 'base_currency', 'country']
