from django.contrib import admin
from .models import TransactionProfitLedger, PnLDailySnapshot, ExposureSnapshot, SpreadSnapshot


@admin.register(TransactionProfitLedger)
class TransactionProfitLedgerAdmin(admin.ModelAdmin):
    list_display  = ('fecha', 'transaction_type', 'currency_code', 'branch',
                     'amount_foreign', 'exchange_rate', 'cost_bob', 'profit_bob', 'profit_pct')
    list_filter   = ('transaction_type', 'currency_code', 'branch', 'fecha')
    search_fields = ('transaction__transaction_number', 'currency_code')
    readonly_fields = [f.name for f in TransactionProfitLedger._meta.fields]
    ordering      = ('-created_at',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(PnLDailySnapshot)
class PnLDailySnapshotAdmin(admin.ModelAdmin):
    list_display = ('fecha', 'branch', 'num_ventas', 'ingreso_ventas_bob',
                    'ganancia_bruta_bob', 'gastos_operativos_bob', 'ganancia_neta_bob',
                    'margen_neto_pct', 'calculado_en')
    list_filter  = ('branch', 'fecha')
    ordering     = ('-fecha',)


@admin.register(ExposureSnapshot)
class ExposureSnapshotAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'branch', 'currency_code', 'stock_units',
                    'exposure_bob', 'pct_of_capital', 'unrealized_pnl_bob', 'alert_level')
    list_filter  = ('branch', 'currency_code', 'alert_level')
    ordering     = ('-timestamp',)

    def has_add_permission(self, request):
        return False


@admin.register(SpreadSnapshot)
class SpreadSnapshotAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'currency_code', 'market_type',
                    'buy_rate', 'sell_rate', 'spread_bob', 'spread_pct', 'prima_oficial_pct')
    list_filter  = ('currency_code', 'market_type')
    ordering     = ('-timestamp',)

    def has_add_permission(self, request):
        return False
