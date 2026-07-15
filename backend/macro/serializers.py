from rest_framework import serializers

from .models import MacroIndicator


class MacroIndicatorSerializer(serializers.ModelSerializer):
    series_label = serializers.CharField(source='get_series_display', read_only=True)

    class Meta:
        model = MacroIndicator
        fields = ['series', 'series_label', 'date', 'value', 'unit', 'source', 'fetched_at']
