"""
Management command: seed_data
===============================================================================
Pobla la base de datos con datos de prueba realistas para el ERP Kapitalya.
Cubre TODOS los modelos del sistema y sus relaciones.

Uso:
    python manage.py seed_data                   # seed completo (idempotente)
    python manage.py seed_data --clean           # limpia BD antes de poblar
    python manage.py seed_data --scenario crisis # escenario: crisis de inventario
    python manage.py seed_data --scenario demand # escenario: alta demanda
    python manage.py seed_data --customers 100   # personalizar cantidad de clientes
    python manage.py seed_data --transactions 300

Escenarios:
    normal   (default) - día normal de operaciones
    demand              - alta demanda, muchas transacciones, spreads ajustados
    crisis              - inventario bajo, muchas alertas, transacciones sospechosas
===============================================================================
"""
from __future__ import annotations

import random
import logging
from decimal import Decimal, ROUND_HALF_UP
from datetime import date, timedelta
from typing import Sequence

from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction
from django.utils import timezone

log = logging.getLogger(__name__)


# -------------------------------------------------------------------------
# Datos maestros estáticos (Bolivia, 2026)
# -------------------------------------------------------------------------

CURRENCIES = [
    {'code': 'BOB', 'name_en': 'Boliviano',       'name_es': 'Boliviano',       'symbol': 'Bs.',  'scale_factor': 1,    'is_active': True, 'is_base_currency': True,  'use_exchange_rate': False},
    {'code': 'USD', 'name_en': 'US Dollar',        'name_es': 'Dolar Americano', 'symbol': '$',    'scale_factor': 1,    'is_active': True, 'is_base_currency': False, 'use_exchange_rate': True},
    {'code': 'EUR', 'name_en': 'Euro',             'name_es': 'Euro',            'symbol': 'EUR',  'scale_factor': 1,    'is_active': True, 'is_base_currency': False, 'use_exchange_rate': True},
    {'code': 'CLP', 'name_en': 'Chilean Peso',     'name_es': 'Peso Chileno',    'symbol': 'CLP',  'scale_factor': 1000, 'is_active': True, 'is_base_currency': False, 'use_exchange_rate': True},
    {'code': 'PEN', 'name_en': 'Peruvian Sol',     'name_es': 'Sol Peruano',     'symbol': 'S/.',  'scale_factor': 1,    'is_active': True, 'is_base_currency': False, 'use_exchange_rate': True},
    {'code': 'BRL', 'name_en': 'Brazilian Real',   'name_es': 'Real Brasileno',  'symbol': 'R$',   'scale_factor': 1,    'is_active': True, 'is_base_currency': False, 'use_exchange_rate': True},
    {'code': 'ARS', 'name_en': 'Argentine Peso',   'name_es': 'Peso Argentino',  'symbol': 'ARS',  'scale_factor': 1000, 'is_active': True, 'is_base_currency': False, 'use_exchange_rate': True},
    {'code': 'GBP', 'name_en': 'British Pound',    'name_es': 'Libra Esterlina', 'symbol': 'GBP',  'scale_factor': 1,    'is_active': True, 'is_base_currency': False, 'use_exchange_rate': True},
]

BRANCHES = [
    {'code': 'CENT', 'name': 'Sucursal Central',  'address': 'Av. Mcal. Santa Cruz 1234, La Paz',   'phone': '2-2345678'},
    {'code': 'SUR',  'name': 'Sucursal Sur',       'address': 'Av. Hernando Siles 500, La Paz',      'phone': '2-7654321'},
    {'code': 'ALTO', 'name': 'Sucursal El Alto',   'address': 'Av. Juan Pablo II 890, El Alto',      'phone': '2-8123456'},
]

# ExchangeRateSources
RATE_SOURCES = [
    {'name': 'Binance P2P',       'source_type': 'digital',       'priority': 8,  'weight': '1.20', 'fetch_interval_min': 15},
    {'name': 'Airtm Digital',     'source_type': 'digital',       'priority': 7,  'weight': '1.10', 'fetch_interval_min': 30},
    {'name': 'Mercado Paralelo',  'source_type': 'parallel',      'priority': 6,  'weight': '1.30', 'fetch_interval_min': 30},
]

# Tasas vigentes por divisa: mercado paralelo Bolivia 2026
# buy/sell son tasas del mercado paralelo físico
CURRENT_RATES = {
    'USD': {'buy': '9.3000', 'sell': '9.5000'},
    'EUR': {'buy': '10.0500', 'sell': '10.3000'},
    'CLP': {'buy': '7.2000',  'sell': '7.8007'},   # por 1000 CLP
    'PEN': {'buy': '2.5500',  'sell': '2.6500'},
    'BRL': {'buy': '1.7500',  'sell': '1.8500'},
    'ARS': {'buy': '0.0095',  'sell': '0.0105'},   # por 1000 ARS
    'GBP': {'buy': '11.5000', 'sell': '11.9000'},
}

# Usuarios del sistema por rol y sucursal
USERS_SPEC = [
    # username, first, last, role, branch_code, email, password
    ('admin',     'Administrador', 'Kapitalya',  'ADMIN',      'CENT', 'admin@kapitalya.bo',        'admin1234',      True,  True),
    ('supervisor1','Carlos',       'Mendoza',    'SUPERVISOR', 'CENT', 'cmendoza@kapitalya.bo',     'super1234',      True,  False),
    ('supervisor2','Patricia',     'Vargas',     'SUPERVISOR', 'SUR',  'pvargas@kapitalya.bo',      'super1234',      True,  False),
    ('supervisor3','Roberto',      'Quispe',     'SUPERVISOR', 'ALTO', 'rquispe@kapitalya.bo',      'super1234',      True,  False),
    ('cajero1',   'Juan',          'Mamani',     'CASHIER',    'CENT', 'cajero1@kapitalya.bo',      'cajero1234',     False, False),
    ('cajero2',   'María',         'Condori',    'CASHIER',    'CENT', 'cajero2@kapitalya.bo',      'cajero1234',     False, False),
    ('cajero3',   'Pedro',         'Flores',     'CASHIER',    'SUR',  'cajero3@kapitalya.bo',      'cajero1234',     False, False),
    ('cajero4',   'Ana',           'Mamani',     'CASHIER',    'SUR',  'cajero4@kapitalya.bo',      'cajero1234',     False, False),
    ('cajero5',   'Luis',          'Ticona',     'CASHIER',    'ALTO', 'cajero5@kapitalya.bo',      'cajero1234',     False, False),
    ('cajero6',   'Rosa',          'Choque',     'CASHIER',    'ALTO', 'cajero6@kapitalya.bo',      'cajero1234',     False, False),
]

# Nombres bolivianos realistas para clientes
BOLIVIAN_NAMES = [
    ('Juan Carlos', 'Mamani Quispe'), ('María Elena', 'Condori Flores'),
    ('Pedro Pablo', 'Ticona Huanca'), ('Ana Lucía', 'Choque Mamani'),
    ('Luis Fernando', 'Vargas Roca'), ('Rosa María', 'Apaza Condori'),
    ('Carlos Alberto', 'Quispe Tola'), ('Patricia Inés', 'Flores Quispe'),
    ('Roberto Miguel', 'Huanca Chiri'), ('Claudia Roxana', 'Mamani Choque'),
    ('Marco Antonio', 'Colque Nina'), ('Silvia Mercedes', 'Nina Villca'),
    ('Jorge Daniel', 'Villca Poma'), ('Carla Beatriz', 'Poma Ajata'),
    ('Edwin Rodrigo', 'Ajata Torrez'), ('Sonia Patricia', 'Torrez Limachi'),
    ('Alex Fernando', 'Limachi Cayo'), ('Diana Alejandra', 'Cayo Mamani'),
    ('Freddy Omar', 'Mamani Apaza'), ('Natalia Sofia', 'Apaza Quispe'),
    ('Óscar Daniel', 'Quispe Choque'), ('Verónica Isabel', 'Choque Condori'),
    ('Raúl Gustavo', 'Condori Mamani'), ('Sandra Cecilia', 'Mamani Flores'),
    ('David Ernesto', 'Flores Ticona'), ('Miriam Lorena', 'Ticona Quispe'),
    ('Javier Arturo', 'Quispe Mamani'), ('Fabiola Cristina', 'Mamani Torrez'),
    ('Hugo César', 'Torrez Limachi'), ('Ivonne Maricel', 'Limachi Poma'),
    ('Nelson Ariel', 'Poma Colque'), ('Paola Esther', 'Colque Nina'),
    ('Gabriel Emilio', 'Nina Chiri'), ('Valeria Fernanda', 'Chiri Villca'),
    ('Sergio Alonso', 'Villca Cayo'), ('Elizabeth Carmen', 'Cayo Ajata'),
    ('Marcos Horacio', 'Ajata Huanca'), ('Teresa Yolanda', 'Huanca Apaza'),
    ('Iván Patricio', 'Apaza Torrez'), ('Karina Marisol', 'Torrez Mamani'),
    ('Christian Paul', 'Mamani Quispe'), ('Andrea Mónica', 'Quispe Choque'),
    ('Gonzalo Rubén', 'Choque Flores'), ('Liliana Ruth', 'Flores Condori'),
    ('Mauricio Dante', 'Condori Poma'), ('Susana Griselda', 'Poma Colque'),
    ('Álvaro Sebastián', 'Colque Chiri'), ('Gloria Eugenia', 'Chiri Nina'),
    ('Pablo Esteban', 'Nina Villca'), ('Lorena Beatriz', 'Villca Mamani'),
    # PEP (2 clientes)
    ('Walter Édgar', 'Camacho Ríos'), ('Lourdes Beatriz', 'Morales Suárez'),
    # Extranjeros
    ('John Michael', 'Smith Johnson'), ('Sophie Anne', 'Dupont Martin'),
    ('Carlos Eduardo', 'Fernández García'), ('Amanda Luisa', 'Silva Pereira'),
]

CITIES_BOL = ['La Paz', 'El Alto', 'Cochabamba', 'Santa Cruz', 'Oruro', 'Potosí', 'Sucre', 'Tarija']
NATIONALITIES = ['Boliviana'] * 45 + ['Estadounidense', 'Francesa', 'Colombiana', 'Brasileña', 'Argentina', 'Peruana']

# Tipos de documentos por índice (coherente con NATIONALITIES)
DOCUMENT_TYPES_BY_NATIONALITY = {
    'Boliviana': 'CI', 'Estadounidense': 'PASSPORT', 'Francesa': 'PASSPORT',
    'Colombiana': 'PASSPORT', 'Brasileña': 'PASSPORT', 'Argentina': 'PASSPORT',
    'Peruana': 'PASSPORT',
}

# Categorías de gastos con distribución realista
EXPENSES_DATA = [
    ('ALQUILER',      'Alquiler mensual sucursal',      1800, 'TRANSFER'),
    ('SERVICIOS',     'Factura EPSAS/DELAPAZ',           85, 'EFECTIVO'),
    ('SERVICIOS',     'Internet y telefonía',            200, 'QR'),
    ('SUELDOS',       'Sueldos personal',               6500, 'TRANSFER'),
    ('COMISIONES',    'Comisión transferencia BISA',       45, 'TRANSFER'),
    ('PUBLICIDAD',    'Publicidad Facebook/Instagram',   350, 'TARJETA'),
    ('IMPUESTOS',     'IUE trimestral',                 1200, 'TRANSFER'),
    ('SUMINISTROS',   'Papel, tóner, útiles oficina',    180, 'EFECTIVO'),
    ('MANTENIMIENTO', 'Mantenimiento sistema alarma',    250, 'EFECTIVO'),
    ('TRANSPORTE',    'Mensajería y transporte valores',  90, 'EFECTIVO'),
    ('BANCO',         'Comisión cuenta corriente BNB',   120, 'TRANSFER'),
    ('OTROS',         'Refrigerios y viáticos',          150, 'EFECTIVO'),
]


# -------------------------------------------------------------------------
# Utilidades
# -------------------------------------------------------------------------

def _q(value, places=2) -> Decimal:
    """Quantize a Decimal to N decimal places."""
    exp = Decimal(10) ** -places
    return Decimal(str(value)).quantize(exp, rounding=ROUND_HALF_UP)


def _random_rate_variation(base: Decimal, pct_range: float = 0.02) -> Decimal:
    """Aplica variación aleatoria +/-pct_range al rate base."""
    factor = 1 + random.uniform(-pct_range, pct_range)
    return _q(base * Decimal(str(factor)), 4)


def _dates_range(days_back: int = 30) -> list[date]:
    """Retorna lista de fechas desde days_back días atrás hasta hoy."""
    today = timezone.localdate()
    return [today - timedelta(days=i) for i in range(days_back, -1, -1)]


# -------------------------------------------------------------------------
# Command
# -------------------------------------------------------------------------

class Command(BaseCommand):
    help = 'Seed completo de BD para Kapitalya ERP - datos de prueba realistas'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clean', action='store_true',
            help='Eliminar TODOS los datos antes de sembrar (¡destructivo!)',
        )
        parser.add_argument(
            '--scenario', choices=['normal', 'demand', 'crisis'], default='normal',
            help='Escenario de datos: normal | demand | crisis',
        )
        parser.add_argument(
            '--customers', type=int, default=50,
            help='Cantidad de clientes a generar (default: 50)',
        )
        parser.add_argument(
            '--transactions', type=int, default=150,
            help='Cantidad de transacciones a generar (default: 150)',
        )
        parser.add_argument(
            '--days', type=int, default=30,
            help='Días de historia a generar (default: 30)',
        )

    # --- Punto de entrada ------------------------------------------------

    def handle(self, *args, **options):
        from django.conf import settings as django_settings

        self.scenario    = options['scenario']
        self.n_customers = options['customers']
        self.n_txn       = options['transactions']
        self.days        = options['days']

        self.stdout.write(self.style.MIGRATE_HEADING(
            f'\n+==========================================+\n'
            f'|   Kapitalya ERP - Seed Data              |\n'
            f'|   Escenario: {self.scenario:<28}|\n'
            f'+==========================================+\n'
        ))

        # Allow caja to go negative while seeding historical transactions
        # (no real cash exists yet; signals validate live operations only).
        django_settings.KAPITALYA_ALLOW_NEGATIVE_EFECTIVO = True

        if options['clean']:
            self._clean_database()

        # Each layer runs in its own atomic block so one failure
        # does not poison the rest of the seeding run.
        # Capa 1: Infraestructura
        with db_transaction.atomic():
            self._seed_currencies()
            self._seed_branches()
            self._seed_rate_sources()

        # Capa 2: Tasas de cambio
        with db_transaction.atomic():
            self._seed_exchange_rates()
            self._seed_rate_configurations()

        # Capa 3: Usuarios y clientes
        with db_transaction.atomic():
            self._seed_users()
            self._seed_customers()

        # Capa 4: Inventario
        with db_transaction.atomic():
            self._seed_inventory()

        # Capa 5: Transacciones  (savepoints por tx — ver metodo)
        self._seed_transactions()

        # Capa 6: Alertas
        with db_transaction.atomic():
            self._seed_inventory_alerts()
            self._seed_alert_logs()

        # Capa 7: Analytics
        with db_transaction.atomic():
            self._seed_analytics()

        # Capa 8: Capital
        with db_transaction.atomic():
            self._seed_capital()

        # Capa 9: Predicciones
        with db_transaction.atomic():
            self._seed_predictions()

        # Capa 10: Reportes
        with db_transaction.atomic():
            self._seed_reports()

        self.stdout.write(self.style.SUCCESS(
            '\n[OK]  Seed completo. Sistema listo para pruebas.\n'
            '------------------------------------------\n'
            '  Admin:      admin / admin1234\n'
            '  Supervisor: supervisor1 / super1234\n'
            '  Cajero:     cajero1 / cajero1234\n'
            '------------------------------------------\n'
        ))

    # ---------------------------------------------------------------------
    # LIMPIEZA
    # ---------------------------------------------------------------------

    def _clean_database(self):
        self.stdout.write(self.style.WARNING('\n??  Limpiando base de datos...'))
        from analytics.models import (
            TransactionProfitLedger, PnLDailySnapshot,
            ExposureSnapshot, SpreadSnapshot, CapitalAnomalyLog, DecisionLog,
        )
        from capital.models import (
            Gasto, CapitalSnapshot, CapitalManualEntry,
            CapitalComposicion, CashBOB, CashFlowLog, CapitalEntryHistory,
            CapitalComposicionHistory,
        )
        from predictions.models import PredictionModel, Prediction, TrainingData
        from reports.models import (
            CashTransactionReport, SuspiciousActivityReport,
            PEPRegistry, DailyOperationLog, GeneratedReport,
        )
        from alerts.models import AlertLog
        from inventory.alerts import InventoryAlert
        from inventory.models import InventoryMovement, InventoryTransfer, CurrencyInventory
        from transactions.models import Transaction, Customer
        from rates.models import ExchangeRate, RateConfiguration, ExchangeRateSource, ExchangeRateDecisionLog
        from users.models import User, Branch, AuditLog, UserActivity

        models_to_clear = [
            # Analytics
            TransactionProfitLedger, PnLDailySnapshot, ExposureSnapshot,
            SpreadSnapshot, CapitalAnomalyLog, DecisionLog,
            # Capital
            CashFlowLog, CapitalComposicionHistory, CapitalEntryHistory,
            CapitalComposicion, CapitalManualEntry, CapitalSnapshot, CashBOB, Gasto,
            # Reports
            SuspiciousActivityReport, CashTransactionReport, PEPRegistry,
            DailyOperationLog, GeneratedReport,
            # Predictions
            Prediction, TrainingData, PredictionModel,
            # Alerts
            AlertLog, InventoryAlert,
            # Inventory
            InventoryMovement, InventoryTransfer, CurrencyInventory,
            # Transactions
            Transaction, Customer,
            # Rates
            ExchangeRateDecisionLog, ExchangeRate, RateConfiguration, ExchangeRateSource,
            # Users (no borrar superusers del sistema)
            AuditLog, UserActivity,
        ]
        total = 0
        for model in models_to_clear:
            count, _ = model.objects.all().delete()
            total += count
        # Borrar usuarios no-system
        deleted, _ = User.objects.filter(is_superuser=False).delete()
        total += deleted
        deleted, _ = User.objects.filter(username__in=[u[0] for u in USERS_SPEC]).delete()
        total += deleted
        Branch.objects.all().delete()

        self.stdout.write(self.style.WARNING(f'   Eliminados {total} registros.\n'))

    # ---------------------------------------------------------------------
    # CAPA 1: INFRAESTRUCTURA
    # ---------------------------------------------------------------------

    def _seed_currencies(self):
        from rates.models import Currency
        self.stdout.write('\n[1/10] Divisas...')
        for c in CURRENCIES:
            obj, created = Currency.objects.get_or_create(
                code=c['code'],
                defaults={k: v for k, v in c.items() if k != 'code'},
            )
            mark = '  [+]' if created else '  [ ]'
            self.stdout.write(f'{mark} {obj.code:5} {obj.name_en}')
        self._currencies = {c.code: c for c in Currency.objects.all()}

    def _seed_branches(self):
        from users.models import Branch
        self.stdout.write('\n? Sucursales...')
        for b in BRANCHES:
            obj, created = Branch.objects.get_or_create(
                code=b['code'],
                defaults={k: v for k, v in b.items() if k != 'code'},
            )
            mark = '  [+]' if created else '  .'
            self.stdout.write(f'{mark} {obj.code} - {obj.name}')
        self._branches = {b.code: b for b in Branch.objects.filter(code__in=[b['code'] for b in BRANCHES])}

    def _seed_rate_sources(self):
        from rates.models import ExchangeRateSource
        self.stdout.write('\n? Fuentes de tasas...')
        self._sources = {}
        for s in RATE_SOURCES:
            obj, created = ExchangeRateSource.objects.get_or_create(
                name=s['name'],
                defaults={
                    'source_type':        s['source_type'],
                    'priority':           s['priority'],
                    'weight':             Decimal(s['weight']),
                    'fetch_interval_min': s['fetch_interval_min'],
                    'is_active':          True,
                },
            )
            self._sources[s['name']] = obj
            mark = '  [+]' if created else '  .'
            self.stdout.write(f'{mark} {obj.name}')

    # ---------------------------------------------------------------------
    # CAPA 2: TASAS DE CAMBIO
    # ---------------------------------------------------------------------

    def _seed_exchange_rates(self):
        """
        Crea tasas históricas (últimos N días) y la tasa vigente.
        Fuente única: mercado paralelo boliviano.
        """
        from rates.models import ExchangeRate, Currency
        self.stdout.write(f'\n? Tasas de cambio ({self.days} d?as de historia)...')

        bob = self._currencies['BOB']
        dates = _dates_range(self.days)
        source_paralelo = self._sources.get('Mercado Paralelo')
        created_count   = 0

        for code, base_rates in CURRENT_RATES.items():
            currency = self._currencies.get(code)
            if not currency:
                continue

            buy_base  = Decimal(base_rates['buy'])
            sell_base = Decimal(base_rates['sell'])

            today = timezone.localdate()
            for d in dates:
                # Variación +/-2% por día para simular volatilidad
                buy_var  = _random_rate_variation(buy_base,  pct_range=0.018)
                sell_var = _random_rate_variation(sell_base, pct_range=0.015)
                # Asegurar buy < sell siempre
                if buy_var >= sell_var:
                    sell_var = _q(buy_var * Decimal('1.02'), 4)

                dt = timezone.make_aware(
                    timezone.datetime.combine(d, timezone.datetime.min.time().replace(hour=8))
                )
                # Historical rates expire at end of day; only today's rate stays active.
                # This prevents SpreadService.guardar_snapshot() from processing stale rates.
                is_today = (d == today)
                valid_until_val = None if is_today else timezone.make_aware(
                    timezone.datetime.combine(d, timezone.datetime.min.time().replace(hour=23, minute=59))
                )

                # Tasa paralela física - sin restricción de desviación BCB
                exists = ExchangeRate.objects.filter(
                    currency_from=currency,
                    currency_to=bob,
                    valid_from=dt,
                    market_type='paralelo_fisico_empresa',
                    rate_source=source_paralelo,
                ).exists()

                if not exists:
                    avg_var = _q((buy_var + sell_var) / Decimal('2'), 4)
                    ExchangeRate.objects.create(
                        currency_from=currency,
                        currency_to=bob,
                        official_rate=avg_var,
                        buy_rate=buy_var,
                        sell_rate=sell_var,
                        avg_rate=avg_var,
                        source_method='MANUAL',
                        market_type='paralelo_fisico_empresa',
                        rate_source=source_paralelo,
                        source='Paralelo Fisico',
                        valid_from=dt,
                        valid_until=valid_until_val,
                    )
                    created_count += 1

        self.stdout.write(f'  [+] {created_count} tasas creadas para {len(CURRENT_RATES)} pares de divisas')

    def _seed_rate_configurations(self):
        from rates.models import RateConfiguration, Currency
        self.stdout.write('\n??  Configuraciones de tasas...')
        bob = self._currencies['BOB']
        configs = [
            ('USD', '0.30', '0.50', '0.25', '0.45', '0.20', '0.40', 100,  10000),
            ('EUR', '0.35', '0.55', '0.30', '0.50', '0.25', '0.45', 50,   8007),
            ('CLP', '0.40', '0.60', '0.35', '0.55', '0.30', '0.50', 100,  5000),
            ('PEN', '0.30', '0.50', '0.25', '0.45', '0.20', '0.40', 100,  5000),
            ('BRL', '0.35', '0.55', '0.30', '0.50', '0.25', '0.45', 50,   3000),
            ('GBP', '0.30', '0.50', '0.25', '0.45', '0.20', '0.40', 50,   5000),
        ]
        for (code, bm, sm, ba, sa, be, se, min_a, max_a) in configs:
            cur = self._currencies.get(code)
            if not cur:
                continue
            obj, created = RateConfiguration.objects.get_or_create(
                currency_from=cur,
                currency_to=bob,
                defaults={
                    'buy_margin_morning':    Decimal(bm),
                    'sell_margin_morning':   Decimal(sm),
                    'buy_margin_afternoon':  Decimal(ba),
                    'sell_margin_afternoon': Decimal(sa),
                    'buy_margin_evening':    Decimal(be),
                    'sell_margin_evening':   Decimal(se),
                    'min_transaction_amount': Decimal(str(min_a)),
                    'max_transaction_amount': Decimal(str(max_a)),
                    'is_active': True,
                },
            )
            mark = '  [+]' if created else '  .'
            self.stdout.write(f'{mark} {code}/BOB  margen_mañana={bm}/{sm}%')

    # ---------------------------------------------------------------------
    # CAPA 3: USUARIOS Y CLIENTES
    # ---------------------------------------------------------------------

    def _seed_users(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        self.stdout.write('\n? Usuarios del sistema...')
        self._users = {}
        hashed_passwords = {}

        for spec in USERS_SPEC:
            username, first, last, role, bcode, email, pwd, is_staff, is_su = spec
            branch = self._branches.get(bcode)
            if pwd not in hashed_passwords:
                hashed_passwords[pwd] = make_password(pwd)

            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    'first_name': first,
                    'last_name':  last,
                    'email':      email,
                    'role':       role,
                    'branch':     branch,
                    'is_staff':   is_staff,
                    'is_superuser': is_su,
                    'is_active':  True,
                    'password':   hashed_passwords[pwd],
                },
            )
            if not created and not user.password.startswith('pbkdf2'):
                user.set_password(pwd)
                user.save(update_fields=['password'])
            self._users[username] = user
            mark = '  [+]' if created else '  .'
            self.stdout.write(f'{mark} {username:15} [{role:10}] {bcode}')

    def _seed_customers(self):
        from transactions.models import Customer
        self.stdout.write(f'\n? Clientes ({self.n_customers})...')

        if Customer.objects.count() >= self.n_customers:
            self.stdout.write('  [ ] Ya existen suficientes clientes, omitiendo.')
            self._customers = list(Customer.objects.all()[:self.n_customers])
            return

        self._customers = list(Customer.objects.all())
        existing_docs = set(Customer.objects.values_list('document_number', flat=True))

        names_pool = BOLIVIAN_NAMES * 10  # repetir para cubrir n_customers
        random.shuffle(names_pool)

        to_create = []
        pep_indices = random.sample(range(self.n_customers), min(3, self.n_customers))

        for i in range(self.n_customers - len(self._customers)):
            first_name, last_name = names_pool[i % len(BOLIVIAN_NAMES)]
            full_name = f"{first_name} {last_name}"
            nationality = NATIONALITIES[i % len(NATIONALITIES)]
            doc_type = DOCUMENT_TYPES_BY_NATIONALITY.get(nationality, 'CI')

            # Generar CI/doc único
            for attempt in range(100):
                if doc_type == 'CI':
                    doc_num = str(random.randint(1_000_000, 9_999_999))
                    if nationality != 'Boliviana':
                        doc_num += random.choice(['LP', 'CB', 'SC', 'OR', 'PT'])
                else:
                    # Passport: 2 letras + 6 dígitos
                    letters = ''.join(random.choices('ABCDEFGHJKLMNPQRSTUVWXYZ', k=2))
                    doc_num = letters + str(random.randint(100000, 999999))
                if doc_num not in existing_docs:
                    existing_docs.add(doc_num)
                    break

            birth_year  = random.randint(1950, 2000)
            birth_month = random.randint(1, 12)
            birth_day   = random.randint(1, 28)

            to_create.append(Customer(
                document_type=doc_type,
                document_number=doc_num,
                full_name=full_name,
                phone=f'+591 7{random.randint(1000000,9999999)}',
                email=f'{first_name.lower().replace(" ",".")}.{last_name.split()[0].lower()}_{i}@email.com',
                address=f'{random.choice(CITIES_BOL)}, {random.choice(["Calle", "Av.", "Pasaje"])} {random.randint(1,999)}',
                birth_date=date(birth_year, birth_month, birth_day),
                nationality=nationality,
                is_pep=(i in pep_indices),
                is_frequent=(i % 5 == 0),
                notes='Cliente seed' if i < 5 else '',
            ))

        if to_create:
            created_batch = Customer.objects.bulk_create(to_create, ignore_conflicts=True)
            self.stdout.write(f'  [+] {len(created_batch)} clientes creados')
        self._customers = list(Customer.objects.all()[:self.n_customers])
        self.stdout.write(f'  [ ] Total clientes: {len(self._customers)}')

    # ---------------------------------------------------------------------
    # CAPA 4: INVENTARIO
    # ---------------------------------------------------------------------

    def _seed_inventory(self):
        from inventory.models import CurrencyInventory
        self.stdout.write('\n? Inventario de divisas...')

        # Stock inicial por divisa y sucursal
        # (physical_balance, wac, min_stock, max_stock, reorder)
        stock_config = {
            'USD': (5000,  9.30, 1000, 30000, 2000),
            'EUR': (2000, 10.05,  500, 15000, 1000),
            'CLP': (1500,  7.50,  200, 10000,  500),
            'PEN': (3000,  2.55,  500, 20000, 1000),
            'BRL': (1000,  1.75,  300,  8007,  600),
            'ARS': ( 200,  0.010,  50,  2000,  100),
            'GBP': ( 500, 11.50,  100,  5000,  200),
        }

        # En crisis: reducir stock para disparar alertas
        if self.scenario == 'crisis':
            stock_config['USD'] = (500, 9.30, 1000, 30000, 2000)   # bajo mínimo
            stock_config['EUR'] = (200, 10.05, 500, 15000, 1000)   # bajo mínimo
            stock_config['BRL'] = (8500, 1.75, 300, 8007, 600)     # sobre máximo

        self._inventories = {}
        created_count = 0

        for branch in self._branches.values():
            self._inventories[branch.code] = {}
            for code, (phys, wac, mn, mx, rp) in stock_config.items():
                currency = self._currencies.get(code)
                if not currency:
                    continue

                # Variación por sucursal
                phys_var = _q(Decimal(str(phys)) * Decimal(str(random.uniform(0.7, 1.3))), 2)

                inv, created = CurrencyInventory.objects.get_or_create(
                    currency=currency,
                    branch=branch,
                    defaults={
                        'physical_balance':      phys_var,
                        'digital_balance':       _q(phys_var * Decimal('0.1'), 2),
                        'weighted_average_cost': Decimal(str(wac)),
                        'minimum_stock':         Decimal(str(mn)),
                        'maximum_stock':         Decimal(str(mx)),
                        'reorder_point':         Decimal(str(rp)),
                    },
                )
                self._inventories[branch.code][code] = inv
                if created:
                    created_count += 1

        self.stdout.write(f'  [+] {created_count} inventarios creados')

    # ---------------------------------------------------------------------
    # CAPA 5: TRANSACCIONES
    # ---------------------------------------------------------------------

    def _seed_transactions(self):
        from transactions.models import Transaction

        self.stdout.write(f'\n? Transacciones ({self.n_txn})...')

        existing = Transaction.objects.count()
        if existing >= self.n_txn:
            self.stdout.write(f'  [ ] Ya existen {existing} transacciones, omitiendo.')
            self._transactions = list(Transaction.objects.all()[:self.n_txn])
            return

        bob   = self._currencies['BOB']
        dates = _dates_range(self.days)
        cashiers    = [u for u in self._users.values() if u.role == 'CASHIER']
        supervisors = [u for u in self._users.values() if u.role == 'SUPERVISOR']
        branches    = list(self._branches.values())

        # En alta demanda: más transacciones por día
        txn_per_day = max(1, self.n_txn // max(len(dates), 1))

        # Divisas para transacciones (no BOB)
        trade_currencies = ['USD', 'EUR', 'CLP', 'PEN', 'BRL', 'GBP']
        # Pesos para selección aleatoria (USD más frecuente)
        currency_weights = [50, 20, 10, 8, 7, 5]

        created = 0
        status_choices   = ['COMPLETED', 'COMPLETED', 'COMPLETED', 'COMPLETED', 'PENDING', 'CANCELLED']
        category_choices = ['REPORTABLE', 'REPORTABLE', 'REPORTABLE', 'INTERNA']
        payment_choices  = ['CASH', 'TRANSFER', 'QR', 'TRANSFER', 'TRANSFER']

        self._transactions = []

        for day in dates:
            day_txns = random.randint(max(1, txn_per_day - 3), txn_per_day + 5)
            for _ in range(day_txns):
                if created >= self.n_txn:
                    break

                branch  = random.choice(branches)
                cashier = random.choice([u for u in cashiers if u.branch_id == branch.id] or cashiers)
                supervisor = random.choice(supervisors) if random.random() < 0.1 else None

                cur_code = random.choices(trade_currencies, weights=currency_weights, k=1)[0]
                currency = self._currencies.get(cur_code)
                if not currency:
                    continue

                txn_type = random.choice(['BUY', 'SELL'])
                # Para SELL en crisis: menos montos (inventario bajo)
                if self.scenario == 'crisis' and txn_type == 'SELL':
                    base_amount = random.choice([50, 100, 200])
                elif self.scenario == 'demand':
                    base_amount = random.choice([100, 200, 500, 1000, 2000])
                else:
                    base_amount = random.choice([50, 100, 200, 300, 500, 1000, 1500])

                # Obtener tasa vigente del día (usar tasa base + variación)
                base_rates  = CURRENT_RATES.get(cur_code, {})
                buy_rate_val  = _random_rate_variation(Decimal(base_rates.get('buy',  '6.00')), 0.01)
                sell_rate_val = _random_rate_variation(Decimal(base_rates.get('sell', '6.10')), 0.01)
                if buy_rate_val >= sell_rate_val:
                    sell_rate_val = _q(buy_rate_val * Decimal('1.015'), 4)

                exchange_rate = sell_rate_val if txn_type == 'SELL' else buy_rate_val

                # Invariante: currency_from = divisa extranjera, currency_to = BOB
                # amount_from = entero (sin decimales) para divisas extranjeras
                amount_from = Decimal(str(base_amount))  # ya es entero
                amount_to   = _q(amount_from * exchange_rate, 2)

                # Supervisor requerido para montos grandes
                if cur_code == 'USD' and amount_from > 5000:
                    supervisor = random.choice(supervisors)
                elif cur_code == 'BOB' and amount_from > 35000:
                    supervisor = random.choice(supervisors)

                # Seleccionar método de pago
                payment = random.choices(payment_choices)[0]
                # CASH + USD requiere denomination_type
                denomination = None
                if payment == 'CASH' and cur_code == 'USD':
                    denomination = random.choice(['BILLS', 'SUELTOS', 'SINGLES'])
                    # Asegurar que amount_from sea válido para la denominación
                    if denomination == 'BILLS':
                        amount_from = Decimal(str((base_amount // 50) * 50 or 50))
                    elif denomination == 'SUELTOS':
                        amount_from = Decimal(str((base_amount // 5) * 5 or 5))
                    amount_to = _q(amount_from * exchange_rate, 2)
                elif payment == 'CASH' and cur_code != 'USD' and cur_code != 'BOB':
                    # Otros CASH no-USD: no requieren denomination pero sí integer
                    amount_from = Decimal(str(int(amount_from)))

                # Categoría de transacción
                category = random.choices(category_choices)[0]
                customer = None
                if category == 'REPORTABLE':
                    customer = random.choice(self._customers)

                # Estado y timestamps
                status = random.choices(status_choices)[0]
                txn_datetime = timezone.make_aware(
                    timezone.datetime.combine(
                        day,
                        timezone.datetime.min.time().replace(
                            hour=random.randint(8, 18),
                            minute=random.randint(0, 59),
                        ),
                    )
                )

                # Each tx in its own atomic() — Django auto-creates a savepoint
                # when nested, so signal failures roll back only this tx.
                try:
                    with db_transaction.atomic():
                        txn = Transaction(
                            transaction_type=txn_type,
                            transaction_category=category,
                            status=status,
                            customer=customer,
                            currency_from=currency,
                            currency_to=bob,
                            amount_from=amount_from,
                            amount_to=amount_to,
                            exchange_rate=exchange_rate,
                            payment_method=payment,
                            denomination_type=denomination,
                            cashier=cashier,
                            branch=branch,
                            supervisor=supervisor,
                            notes=f'Tx seed {day} #{created + 1}',
                            receipt_number=f'REC{created+1:06d}',
                        )
                        txn.save()
                    self._transactions.append(txn)
                    created += 1
                except Exception as exc:
                    log.debug('Tx seed omitida: %s', exc)
                    continue

            if created >= self.n_txn:
                break

        self.stdout.write(f'  [+] {created} transacciones creadas')

    # ---------------------------------------------------------------------
    # CAPA 6: ALERTAS
    # ---------------------------------------------------------------------

    def _seed_inventory_alerts(self):
        from inventory.alerts import InventoryAlert
        from inventory.models import CurrencyInventory
        self.stdout.write('\n? Alertas de inventario...')

        if InventoryAlert.objects.count() > 0:
            self.stdout.write('  [ ] Alertas de inventario ya existen.')
            return

        admin = self._users.get('admin')
        created = 0

        alert_scenarios = {
            'normal': [
                ('LOW_STOCK', 'MEDIUM', False),
                ('RECOUNT_NEEDED', 'LOW', False),
            ],
            'demand': [
                ('LOW_STOCK', 'HIGH', False),
                ('LOW_STOCK', 'HIGH', False),
                ('RECOUNT_NEEDED', 'LOW', False),
                ('OVERSTOCK', 'MEDIUM', False),
            ],
            'crisis': [
                ('LOW_STOCK', 'CRITICAL', False),
                ('LOW_STOCK', 'CRITICAL', False),
                ('LOW_STOCK', 'HIGH', False),
                ('SIGNIFICANT_ADJUSTMENT', 'HIGH', False),
                ('OVERSTOCK', 'MEDIUM', True),
            ],
        }

        inventories = list(CurrencyInventory.objects.select_related('currency', 'branch').all()[:10])
        if not inventories:
            return

        for i, (alert_type, severity, is_resolved) in enumerate(alert_scenarios[self.scenario]):
            inv = inventories[i % len(inventories)]
            alert = InventoryAlert(
                inventory=inv,
                alert_type=alert_type,
                severity=severity,
                message='',    # auto-generado en save()
                data={'stock': float(inv.total_balance), 'minimum': float(inv.minimum_stock)},
                triggered_by=admin,
                is_resolved=is_resolved,
            )
            if is_resolved:
                alert.resolved_by = admin
                alert.resolved_at = timezone.now()
            alert.save()
            created += 1

        self.stdout.write(f'  [+] {created} alertas de inventario')

    def _seed_alert_logs(self):
        from alerts.models import AlertLog
        self.stdout.write('\n? AlertLog (sistema)...')

        if AlertLog.objects.count() > 0:
            self.stdout.write('  [ ] AlertLogs ya existen.')
            return

        admin      = self._users.get('admin')
        branches   = list(self._branches.values())
        supervisor = self._users.get('supervisor1')

        alert_templates = [
            # (source, alert_type, severity, title, message, acknowledged)
            ('INVENTORY', 'LOW_STOCK_USD',        'HIGH',     'Stock USD bajo mínimo',
             'El inventario USD en Sucursal Central está al 35% del mínimo requerido.',
             False),
            ('RATES',     'RATE_DEVIATION',        'MEDIUM',   'Desviación de tasa EUR',
             'La tasa EUR/BOB se desvió 3.2% de la referencia BCB.',
             False),
            ('TRANSACTION','HIGH_VALUE_TRANSACTION','HIGH',    'Transacción de alto valor',
             'Se procesó una compra de USD 8,500 que requiere revisión ASFI.',
             True),
            ('ANOMALY',   'UNUSUAL_VOLUME',        'MEDIUM',   'Volumen inusual detectado',
             'El volumen de transacciones en la última hora supera 3x el promedio.',
             False),
            ('SYSTEM',    'CELERY_WORKER_DOWN',    'CRITICAL', 'Worker Celery caído',
             'El worker de Celery no responde desde hace 15 minutos.',
             True),
            ('SNAPSHOT',  'CAPITAL_DROP',          'HIGH',     'Caída de capital detectada',
             'El capital total cayó 4.2% en la última hora.',
             False),
            ('RIESGO',    'EXPOSURE_HIGH',         'MEDIUM',   'Alta exposición USD',
             'El 58% del capital está concentrado en USD. Riesgo de concentración.',
             False),
            ('OPERATIVO', 'CASHIER_LIMIT_REACHED', 'LOW',      'Cajero cerca del límite',
             'cajero2 ha procesado 45 transacciones hoy. Límite: 50.',
             True),
            ('PRECIO',    'SPREAD_BELOW_MIN',      'MEDIUM',   'Spread EUR por debajo del mínimo',
             'El spread EUR/BOB cayó a 0.18%, por debajo del mínimo rentable (0.30%).',
             False),
            ('OPORTUNIDAD','RATE_SPIKE_USD',       'LOW',      'Spike de tasa USD',
             'La tasa USD en el mercado paralelo subió 1.5% en los últimos 30 min.',
             False),
        ]

        # Crisis: agregar más alertas críticas
        if self.scenario == 'crisis':
            alert_templates += [
                ('INVENTORY', 'CRITICAL_STOCK_USD', 'CRITICAL', '¡Stock USD agotado!',
                 'El inventario USD llegó a cero. No se pueden procesar ventas.',
                 False),
                ('ANOMALY',   'NEGATIVE_BALANCE',   'CRITICAL', 'Balance negativo detectado',
                 'El balance físico de EUR es negativo. Verificar inmediatamente.',
                 False),
                ('RATES',     'RATE_INVERTED',       'CRITICAL', 'Tasa invertida BRL',
                 'La tasa de compra BRL supera la tasa de venta. Spread negativo.',
                 False),
            ]

        created = 0
        for i, (src, atype, sev, title, msg, acked) in enumerate(alert_templates):
            branch = branches[i % len(branches)]
            alert = AlertLog(
                source=src,
                alert_type=atype,
                severity=sev,
                title=title,
                message=msg,
                accion_sugerida=f'Revisar {atype.lower().replace("_", " ")} de inmediato.',
                data={'generated_by': 'seed', 'index': i},
                branch=branch,
                triggered_by=admin,
                is_acknowledged=acked,
                acknowledged_by=supervisor if acked else None,
                acknowledged_at=timezone.now() if acked else None,
            )
            alert.save()
            created += 1

        self.stdout.write(f'  [+] {created} alertas del sistema')

    # ---------------------------------------------------------------------
    # CAPA 7: ANALYTICS
    # ---------------------------------------------------------------------

    def _seed_analytics(self):
        from analytics.models import (
            TransactionProfitLedger, PnLDailySnapshot,
            ExposureSnapshot, SpreadSnapshot, CapitalAnomalyLog, DecisionLog,
        )
        from transactions.models import Transaction
        self.stdout.write('\n? Analytics...')

        admin    = self._users.get('admin')
        branches = list(self._branches.values())
        dates    = _dates_range(self.days)
        bob_rate = Decimal('1.0')

        # -- TransactionProfitLedger -------------------------------------------
        if not TransactionProfitLedger.objects.exists():
            completed_txns = Transaction.objects.filter(
                status='COMPLETED',
                transaction_type='SELL',
            ).select_related('currency_from', 'branch')[:min(50, self.n_txn // 3)]

            ledger_batch = []
            for txn in completed_txns:
                wac_val  = Decimal(CURRENT_RATES.get(txn.currency_from.code, {}).get('buy', '6.00'))
                cost_bob = _q(txn.amount_from * wac_val, 2)
                profit   = _q(txn.amount_to - cost_bob, 2)
                profit_pct = _q(profit / cost_bob * 100, 4) if cost_bob else Decimal('0')
                spread_bob = _q(txn.exchange_rate - wac_val, 4)
                ledger_batch.append(TransactionProfitLedger(
                    transaction=txn,
                    transaction_type='SELL',
                    currency_code=txn.currency_from.code,
                    branch=txn.branch,
                    fecha=txn.created_at.date() if txn.created_at else timezone.localdate(),
                    amount_foreign=txn.amount_from,
                    exchange_rate=txn.exchange_rate,
                    amount_bob=txn.amount_to,
                    wac_at_transaction=wac_val,
                    wac_after_transaction=wac_val,
                    cost_bob=cost_bob,
                    profit_bob=profit,
                    profit_pct=profit_pct,
                    spread_bob=spread_bob,
                ))
            if ledger_batch:
                TransactionProfitLedger.objects.bulk_create(ledger_batch)
            self.stdout.write(f'  [+] {len(ledger_batch)} entradas TransactionProfitLedger')

        # -- PnLDailySnapshot ---------------------------------------------
        if not PnLDailySnapshot.objects.exists():
            snapshots = []
            for branch in branches:
                for d in dates:
                    num_ventas = random.randint(5, 30)
                    ing        = _q(Decimal(str(random.uniform(5000, 50000))), 2)
                    costo      = _q(ing * Decimal('0.985'), 2)
                    bruta      = _q(ing - costo, 2)
                    gastos     = _q(Decimal(str(random.uniform(200, 800))), 2)
                    neta       = _q(bruta - gastos, 2)
                    margen     = _q(neta / ing * 100, 4) if ing else Decimal('0')
                    snapshots.append(PnLDailySnapshot(
                        fecha=d,
                        branch=branch,
                        num_ventas=num_ventas,
                        num_compras=random.randint(3, 20),
                        ingreso_ventas_bob=ing,
                        costo_ventas_bob=costo,
                        ganancia_bruta_bob=bruta,
                        inversion_compras_bob=_q(Decimal(str(random.uniform(3000, 30000))), 2),
                        gastos_operativos_bob=gastos,
                        ganancia_neta_bob=neta,
                        margen_neto_pct=margen,
                    ))
            PnLDailySnapshot.objects.bulk_create(snapshots, ignore_conflicts=True)
            self.stdout.write(f'  [+] {len(snapshots)} PnLDailySnapshot')

        # -- ExposureSnapshot ---------------------------------------------
        if not ExposureSnapshot.objects.exists():
            exp_batch = []
            now = timezone.now()
            currencies_exposure = ['USD', 'EUR', 'CLP', 'PEN']
            total_capital = Decimal('350000')
            for branch in branches:
                for code in currencies_exposure:
                    rates_data = CURRENT_RATES.get(code, {})
                    sell_rate = Decimal(rates_data.get('sell', '6.10'))
                    wac       = Decimal(rates_data.get('buy',  '6.00'))
                    inv       = self._inventories.get(branch.code, {}).get(code)
                    stock     = inv.total_balance if inv else Decimal('1000')
                    exposure  = _q(stock * sell_rate, 2)
                    pct       = _q(exposure / total_capital * 100, 4)
                    unreal    = _q((sell_rate - wac) * stock, 2)
                    level     = 'CRITICAL' if pct > 60 else ('WARNING' if pct > 40 else 'OK')
                    cur_obj   = self._currencies.get(code)
                    exp_batch.append(ExposureSnapshot(
                        timestamp=now - timedelta(hours=random.randint(0, 6)),
                        branch=branch,
                        currency_code=code,
                        currency_name=cur_obj.name_en if cur_obj else code,
                        scale_factor=cur_obj.scale_factor if cur_obj else 1,
                        stock_units=stock,
                        wac=wac,
                        sell_rate_unit=sell_rate,
                        sell_rate_lote=sell_rate,
                        exposure_bob=exposure,
                        pct_of_capital=pct,
                        unrealized_pnl_bob=unreal,
                        alert_level=level,
                    ))
            ExposureSnapshot.objects.bulk_create(exp_batch)
            self.stdout.write(f'  [+] {len(exp_batch)} ExposureSnapshot')

        # -- SpreadSnapshot -----------------------------------------------
        if not SpreadSnapshot.objects.exists():
            spread_batch = []
            for d in dates:
                for code in ['USD', 'EUR', 'CLP']:
                    rates_data = CURRENT_RATES.get(code, {})
                    buy_r  = _random_rate_variation(Decimal(rates_data.get('buy',  '6.00')), 0.01)
                    sell_r = _random_rate_variation(Decimal(rates_data.get('sell', '6.10')), 0.01)
                    if buy_r >= sell_r:
                        sell_r = _q(buy_r * Decimal('1.02'), 4)
                    off_r  = _q((buy_r + sell_r) / Decimal('2'), 4)
                    spread = _q(sell_r - buy_r, 4)
                    spread_pct = _q(spread / buy_r * 100, 4) if buy_r else Decimal('0')
                    prima      = Decimal('0')
                    spread_batch.append(SpreadSnapshot(
                        timestamp=timezone.make_aware(
                            timezone.datetime.combine(d, timezone.datetime.min.time().replace(hour=12))
                        ),
                        currency_code=code,
                        market_type='paralelo_fisico_empresa',
                        buy_rate=buy_r,
                        sell_rate=sell_r,
                        official_rate=off_r,
                        spread_bob=spread,
                        spread_pct=spread_pct,
                        prima_oficial_pct=prima,
                    ))
            SpreadSnapshot.objects.bulk_create(spread_batch)
            self.stdout.write(f'  [+] {len(spread_batch)} SpreadSnapshot')

        # -- CapitalAnomalyLog ---------------------------------------------
        if not CapitalAnomalyLog.objects.exists():
            anomaly_data = [
                ('RATE_SPREAD_HIGH',   'WARNING',  branches[0], 'USD', 'Spread USD 16.5% sobre mid paralelo', 16.5, 15.0),
                ('SPREAD_BELOW_MIN',   'WARNING',  branches[0], 'EUR', 'Spread 0.22% bajo el mínimo', 0.22, 0.30),
                ('EXPOSURE_HIGH',      'CRITICAL', branches[1], 'USD', 'Exposición USD 62% del capital', 62, 60),
                ('RATE_STALE',         'WARNING',  branches[2], 'BRL', 'Tasa BRL sin actualizar 3h', 3, 2),
            ]
            if self.scenario == 'crisis':
                anomaly_data += [
                    ('CAPITAL_DROP',    'CRITICAL', branches[0], '',    'Capital cayó 5.8% en 1h', 5.8, 5.0),
                    ('NEGATIVE_BALANCE','CRITICAL', branches[0], 'EUR', 'Balance EUR negativo', -150, 0),
                    ('MISSING_CASH',    'CRITICAL', branches[1], '',    'Diferencia caja Bs.620', 620, 500),
                ]
            anom_batch = [
                CapitalAnomalyLog(
                    rule=rule, severity=sev, branch=br, currency=cur,
                    description=desc,
                    value=Decimal(str(val)), threshold=Decimal(str(thresh)),
                    details={'seed': True},
                    resolved=(i % 3 == 0),
                    resolved_at=timezone.now() if i % 3 == 0 else None,
                    resolved_by=admin if i % 3 == 0 else None,
                )
                for i, (rule, sev, br, cur, desc, val, thresh) in enumerate(anomaly_data)
            ]
            CapitalAnomalyLog.objects.bulk_create(anom_batch)
            self.stdout.write(f'  [+] {len(anom_batch)} CapitalAnomalyLog')

        # -- DecisionLog --------------------------------------------------
        if not DecisionLog.objects.exists():
            dec_batch = []
            currencies_dec = ['USD', 'EUR', 'CLP']
            decisions = ['COMPRAR', 'VENDER', 'ESPERAR', 'COMPRAR', 'ESPERAR']
            riesgos   = ['BAJO', 'MEDIO', 'ALTO', 'BAJO', 'MEDIO']
            for i, d in enumerate(dates[:20]):
                for code in currencies_dec:
                    rates_d = CURRENT_RATES.get(code, {})
                    dec     = decisions[i % len(decisions)]
                    dec_batch.append(DecisionLog(
                        timestamp=timezone.make_aware(
                            timezone.datetime.combine(d, timezone.datetime.min.time().replace(hour=10))
                        ),
                        currency=code,
                        branch=branches[i % len(branches)],
                        requested_by=admin,
                        decision=dec,
                        confianza=random.randint(55, 95),
                        riesgo=riesgos[i % len(riesgos)],
                        precio_compra=Decimal(rates_d.get('buy', '6.00')),
                        precio_venta=Decimal(rates_d.get('sell', '6.10')),
                        motivo=f'Análisis automático {d}. Tendencia: {dec}.',
                        score_total=_q(Decimal(str(random.uniform(50, 90))), 2),
                        input_snapshot={'tasas': rates_d, 'seed': True},
                        full_result={'decision': dec, 'seed': True},
                    ))
            DecisionLog.objects.bulk_create(dec_batch)
            self.stdout.write(f'  [+] {len(dec_batch)} DecisionLog')

    # ---------------------------------------------------------------------
    # CAPA 8: CAPITAL
    # ---------------------------------------------------------------------

    def _seed_capital(self):
        from capital.models import (
            Gasto, CapitalManualEntry, CapitalSnapshot,
            CapitalComposicion, CashBOB, CashFlowLog,
        )
        from transactions.models import Transaction
        self.stdout.write('\n? Capital y caja...')

        today    = timezone.localdate()
        branches = list(self._branches.values())
        admin    = self._users.get('admin')
        cashiers = [u for u in self._users.values() if u.role == 'CASHIER']
        dates    = _dates_range(self.days)

        # -- Gastos operativos ---------------------------------------------
        if not Gasto.objects.exists():
            gastos_batch = []
            for d in dates:
                # 2-4 gastos por día aleatoriamente
                for _ in range(random.randint(1, 3)):
                    gd = random.choice(EXPENSES_DATA)
                    cat, desc, monto_base, medio = gd
                    branch = random.choice(branches)
                    cajero = random.choice(cashiers)
                    monto  = _q(Decimal(str(monto_base)) * Decimal(str(random.uniform(0.8, 1.2))), 2)
                    gastos_batch.append(Gasto(
                        fecha=d,
                        categoria=cat,
                        descripcion=desc,
                        monto_bob=monto,
                        medio_pago=medio,
                        proveedor=f'Proveedor {cat.capitalize()} SRL',
                        nro_factura=f'FAC-{random.randint(10000, 99999)}',
                        branch=branch,
                        registrado_por=cajero,
                    ))
            Gasto.objects.bulk_create(gastos_batch)
            self.stdout.write(f'  [+] {len(gastos_batch)} gastos operativos')

        # -- CapitalManualEntry (1 por sucursal por día) -----------------------
        if not CapitalManualEntry.objects.exists():
            entries = []
            for branch in branches:
                for d in dates[-7:]:  # última semana
                    entries.append(CapitalManualEntry(
                        branch=branch,
                        fecha=d,
                        efectivo_bob=_q(Decimal(str(random.uniform(5000, 20000))), 2),
                        qr_bob=_q(Decimal(str(random.uniform(1000, 8007))), 2),
                        pasivos_bob=_q(Decimal(str(random.uniform(0, 3000))), 2),
                        notas='Ingreso manual seed',
                        registrado_por=admin,
                    ))
            CapitalManualEntry.objects.bulk_create(entries, ignore_conflicts=True)
            self.stdout.write(f'  [+] {len(entries)} CapitalManualEntry')

        # -- CapitalSnapshot -----------------------------------------------
        if not CapitalSnapshot.objects.exists():
            snaps = []
            for branch in branches:
                for d in dates:
                    efectivo = _q(Decimal(str(random.uniform(8007, 25000))), 2)
                    qr       = _q(Decimal(str(random.uniform(2000, 10000))), 2)
                    divisas  = _q(Decimal(str(random.uniform(40000, 120000))), 2)
                    tarjetas = _q(Decimal(str(random.uniform(500, 3000))), 2)
                    pasivos  = _q(Decimal(str(random.uniform(0, 5000))), 2)
                    total    = _q(efectivo + qr + divisas + tarjetas - pasivos, 2)
                    snaps.append(CapitalSnapshot(
                        fecha=d,
                        branch=branch,
                        efectivo_bob=efectivo,
                        qr_bob=qr,
                        divisas_bob=divisas,
                        tarjetas_bob=tarjetas,
                        pasivos_bob=pasivos,
                        total_bob=total,
                        detalle_divisas={'USD': float(divisas * Decimal('0.6')),
                                         'EUR': float(divisas * Decimal('0.3')),
                                         'otros': float(divisas * Decimal('0.1'))},
                        detalle_tarjetas={},
                        tipo=random.choice(['CIERRE', 'APERTURA', 'MANUAL']),
                        generado_por=admin,
                    ))
            CapitalSnapshot.objects.bulk_create(snaps)
            self.stdout.write(f'  [+] {len(snaps)} CapitalSnapshot')

        # -- CapitalComposicion (1 por sucursal hoy) ---------------------------
        if not CapitalComposicion.objects.filter(fecha=today).exists():
            for branch in branches:
                CapitalComposicion.objects.get_or_create(
                    branch=branch,
                    fecha=today,
                    defaults={
                        'fuertes':          _q(Decimal(str(random.uniform(5000, 15000))), 2),
                        'caja_chica':       _q(Decimal(str(random.uniform(500, 2000))), 2),
                        'monedas':          _q(Decimal(str(random.uniform(50, 300))), 2),
                        'rotos':            _q(Decimal(str(random.uniform(0, 200))), 2),
                        'sueltos':          _q(Decimal(str(random.uniform(200, 1000))), 2),
                        'qr_transferencias':_q(Decimal(str(random.uniform(2000, 8007))), 2),
                        'tarjetas_telefonicas': _q(Decimal(str(random.uniform(100, 500))), 2),
                        'pasivos':          _q(Decimal(str(random.uniform(0, 2000))), 2),
                        'registrado_por':   admin,
                    },
                )
            self.stdout.write(f'  [+] CapitalComposicion para {len(branches)} sucursales')

        # -- CashBOB (1 por sucursal hoy) -------------------------------------
        if not CashBOB.objects.filter(fecha=today).exists():
            for branch in branches:
                CashBOB.objects.get_or_create(
                    branch=branch,
                    fecha=today,
                    defaults={
                        'fuertes_200':   random.randint(5, 30),
                        'fuertes_100':   random.randint(10, 50),
                        'fuertes_50':    random.randint(10, 40),
                        'sueltos_20':    random.randint(20, 80),
                        'sueltos_10':    random.randint(30, 100),
                        'caja_chica_200':random.randint(2, 15),
                        'caja_chica_100':random.randint(5, 20),
                        'caja_chica_50': random.randint(5, 25),
                        'caja_chica_20': random.randint(10, 40),
                        'caja_chica_10': random.randint(20, 60),
                        'qr_transferencias': _q(Decimal(str(random.uniform(1000, 5000))), 2),
                        'registrado_por': admin,
                    },
                )
            self.stdout.write(f'  [+] CashBOB para {len(branches)} sucursales')

        # -- CashFlowLog --------------------------------------------------
        if not CashFlowLog.objects.exists():
            completed_txns = list(Transaction.objects.filter(status='COMPLETED')[:30])
            cashflow_batch = []
            for txn in completed_txns:
                tipo      = 'IN'  if txn.transaction_type == 'SELL' else 'OUT'
                saldo_ant = _q(Decimal(str(random.uniform(5000, 20000))), 2)
                monto     = txn.amount_to
                saldo_res = saldo_ant + monto if tipo == 'IN' else saldo_ant - monto
                concepto  = (f"{'VENTA' if tipo == 'IN' else 'COMPRA'} "
                             f"{txn.currency_from.code} x {txn.amount_from}")
                cashflow_batch.append(CashFlowLog(
                    transaction=txn,
                    tipo=tipo,
                    concepto=concepto,
                    monto_bob=monto,
                    campo_afectado='fuertes' if txn.payment_method == 'CASH' else 'qr_transferencias',
                    saldo_anterior=saldo_ant,
                    saldo_resultante=saldo_res,
                    branch=txn.branch,
                    fecha=txn.created_at.date() if txn.created_at else today,
                ))
            CashFlowLog.objects.bulk_create(cashflow_batch)
            self.stdout.write(f'  [+] {len(cashflow_batch)} CashFlowLog')

    # ---------------------------------------------------------------------
    # CAPA 9: PREDICCIONES ML
    # ---------------------------------------------------------------------

    def _seed_predictions(self):
        from predictions.models import PredictionModel, Prediction, TrainingData
        self.stdout.write('\n? Modelos ML y predicciones...')

        # -- PredictionModel -----------------------------------------------
        model_specs = [
            ('Prophet USD/BOB', 'PROPHET', 'USD/BOB'),
            ('LSTM USD/BOB',    'LSTM',    'USD/BOB'),
            ('Prophet EUR/BOB', 'PROPHET', 'EUR/BOB'),
            ('Ensemble USD/BOB','ENSEMBLE','USD/BOB'),
        ]
        self._pred_models = {}
        for name, mtype, pair in model_specs:
            obj, created = PredictionModel.objects.get_or_create(
                model_type=mtype,
                currency_pair=pair,
                defaults={
                    'name':         name,
                    'parameters':   {'horizon': 7, 'seasonality': True},
                    'metrics':      {'mae': round(random.uniform(0.02, 0.08), 4),
                                     'rmse': round(random.uniform(0.03, 0.12), 4),
                                     'mape': round(random.uniform(0.5, 2.0), 4)},
                    'is_active':    True,
                    'last_trained': timezone.now() - timedelta(days=random.randint(1, 7)),
                },
            )
            self._pred_models[f'{mtype}_{pair}'] = obj

        self.stdout.write(f'  [+] {len(self._pred_models)} modelos ML')

        # -- Predictions (próximos 7 días) ------------------------------------
        if not Prediction.objects.exists():
            preds = []
            usd_model = self._pred_models.get('PROPHET_USD/BOB')
            if usd_model:
                base = Decimal('9.40')
                for i in range(7):
                    pred_date = timezone.now() + timedelta(days=i + 1)
                    predicted  = _random_rate_variation(base, 0.02)
                    buy_pred   = _q(predicted * Decimal('0.985'), 4)
                    sell_pred  = _q(predicted * Decimal('1.015'), 4)
                    ci_width   = _q(predicted * Decimal('0.05'), 4)
                    preds.append(Prediction(
                        model=usd_model,
                        currency_pair='USD/BOB',
                        prediction_date=pred_date,
                        predicted_rate=predicted,
                        predicted_buy_rate=buy_pred,
                        predicted_sell_rate=sell_pred,
                        confidence_lower=_q(predicted - ci_width, 4),
                        confidence_upper=_q(predicted + ci_width, 4),
                        confidence_score=round(random.uniform(0.65, 0.92), 4),
                        external_factors={'inflation_bol': 2.1, 'fed_rate': 5.25},
                    ))
            Prediction.objects.bulk_create(preds)
            self.stdout.write(f'  [+] {len(preds)} predicciones (próximos 7 días)')

        # -- TrainingData (histórico 90 días) ----------------------------------
        if not TrainingData.objects.exists():
            training_batch = []
            today = timezone.localdate()
            for pair_code in ['USD/BOB', 'EUR/BOB']:
                base_code = pair_code.split('/')[0]
                base_rate = Decimal(CURRENT_RATES[base_code]['official'])
                rates_arr  = []
                r = base_rate
                for i in range(90):
                    d = today - timedelta(days=90 - i)
                    r = _random_rate_variation(r, 0.008)
                    rates_arr.append(r)

                ma7_arr  = [None] * 6 + [
                    _q(sum(rates_arr[j-6:j+1]) / 7, 4) for j in range(6, 90)
                ]
                ma30_arr = [None] * 29 + [
                    _q(sum(rates_arr[j-29:j+1]) / 30, 4) for j in range(29, 90)
                ]

                for i in range(90):
                    d = today - timedelta(days=90 - i)
                    dt = timezone.make_aware(
                        timezone.datetime.combine(d, timezone.datetime.min.time().replace(hour=12))
                    )
                    training_batch.append(TrainingData(
                        currency_pair=pair_code,
                        date=dt,
                        rate=rates_arr[i],
                        volume=_q(Decimal(str(random.uniform(50000, 500000))), 2),
                        international_rate=rates_arr[i],
                        interest_rate=Decimal('5.25'),
                        inflation_rate=Decimal('2.10'),
                        oil_price=_q(Decimal(str(random.uniform(70, 95))), 2),
                        ma_7=ma7_arr[i],
                        ma_30=ma30_arr[i],
                        volatility=round(random.uniform(0.001, 0.015), 6),
                        source='BCB',
                    ))
            TrainingData.objects.bulk_create(training_batch, ignore_conflicts=True)
            self.stdout.write(f'  [+] {len(training_batch)} datos de entrenamiento (90 días)')

    # ---------------------------------------------------------------------
    # CAPA 10: REPORTES
    # ---------------------------------------------------------------------

    def _seed_reports(self):
        from reports.models import (
            DailyOperationLog, GeneratedReport, PEPRegistry,
        )
        from transactions.models import Customer
        self.stdout.write('\n? Reportes y registros ASFI...')

        admin    = self._users.get('admin')
        branches = list(self._branches.values())
        dates    = _dates_range(self.days)

        # -- DailyOperationLog ---------------------------------------------
        if not DailyOperationLog.objects.exists():
            logs = []
            for branch in branches:
                for d in dates:
                    num_txns = random.randint(10, 60)
                    buy_bob  = _q(Decimal(str(random.uniform(20000, 100000))), 2)
                    sell_bob = _q(Decimal(str(random.uniform(25000, 110000))), 2)
                    profit   = _q((sell_bob - buy_bob) * Decimal('0.015'), 2)
                    status   = 'LOCKED' if d < timezone.localdate() else 'OPEN'
                    logs.append(DailyOperationLog(
                        log_date=d,
                        branch=branch,
                        status=status,
                        total_transactions=num_txns,
                        total_buy_bob=buy_bob,
                        total_sell_bob=sell_bob,
                        total_profit_bob=profit,
                        rte_count=random.randint(0, 5),
                        opening_balance_bob=_q(Decimal(str(random.uniform(30000, 80070))), 2),
                        closing_balance_bob=_q(Decimal(str(random.uniform(30000, 85000))), 2),
                        closed_by=admin if status == 'LOCKED' else None,
                        closed_at=timezone.now() - timedelta(days=(timezone.localdate() - d).days)
                                  if status == 'LOCKED' else None,
                    ))
            DailyOperationLog.objects.bulk_create(logs, ignore_conflicts=True)
            self.stdout.write(f'  [+] {len(logs)} DailyOperationLog')

        # -- GeneratedReport -----------------------------------------------
        if not GeneratedReport.objects.exists():
            report_types = [
                ('RTE_MONTHLY',  'EXCEL'),
                ('PNL_DAILY',    'PDF'),
                ('PNL_MONTHLY',  'EXCEL'),
                ('DAILY_LOG',    'PDF'),
                ('CLIENT_RANKING','EXCEL'),
                ('PROFITABILITY','EXCEL'),
                ('CASHFLOW',     'PDF'),
            ]
            rpt_batch = []
            today = timezone.localdate()
            for rtype, fmt in report_types:
                date_from = today - timedelta(days=30)
                rpt_batch.append(GeneratedReport(
                    report_type=rtype,
                    format=fmt,
                    date_from=date_from,
                    date_to=today,
                    file_path=f'/media/reports/{rtype.lower()}_{today}.{fmt.lower()}',
                    file_size_kb=random.randint(50, 2000),
                    generated_by=admin,
                    parameters={'branch': 'all', 'seed': True},
                ))
            GeneratedReport.objects.bulk_create(rpt_batch)
            self.stdout.write(f'  [+] {len(rpt_batch)} GeneratedReport')

        # -- PEPRegistry (para clientes marcados como PEP) ---------------------
        if not PEPRegistry.objects.exists():
            pep_customers = Customer.objects.filter(is_pep=True)[:3]
            pep_batch = []
            positions = ['Alcalde Municipal', 'Diputado Nacional', 'Concejal Municipal']
            institutions = ['Alcaldía de La Paz', 'Asamblea Legislativa Plurinacional', 'Concejo Municipal El Alto']
            for i, customer in enumerate(pep_customers):
                pep_batch.append(PEPRegistry(
                    customer=customer,
                    position=positions[i % len(positions)],
                    institution=institutions[i % len(institutions)],
                    since_date=date(2021, 1, 1),
                    risk_level='HIGH',
                    enhanced_dd=True,
                    review_date=timezone.localdate() + timedelta(days=90),
                    notes='Registro seed - PEP activo.',
                    registered_by=admin,
                ))
            if pep_batch:
                PEPRegistry.objects.bulk_create(pep_batch)
                self.stdout.write(f'  [+] {len(pep_batch)} PEPRegistry')
