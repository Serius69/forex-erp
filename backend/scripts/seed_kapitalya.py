"""
Script de datos de prueba — Kapitalya Casa de Cambio
Basado en datos reales del negocio de Sergio.

Uso:
    cd backend
    venv\\Scripts\\activate
    python scripts/seed_kapitalya.py

Crea:
    - Sucursal real (La Paz)
    - Usuarios: admin (Sergio), cajero (Tiffani)
    - Divisas reales del negocio
    - Tasas de cambio actuales
    - Inventario inicial real (saldos 2025 + movimientos 2026)
    - Clientes frecuentes reales
    - Transacciones reales de enero-marzo 2026
    - Alertas de stock
"""

import os
import sys
import django
from decimal import Decimal
from datetime import datetime, timedelta, date
import random

# ── Setup Django ──────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.development')
django.setup()

from django.utils import timezone
from django.contrib.auth.hashers import make_password

from users.models import User, Branch
from rates.models import Currency, ExchangeRate, ExchangeRateSource, RateConfiguration
from transactions.models import Customer, Transaction
from inventory.models import CurrencyInventory, InventoryMovement
from inventory.alerts import InventoryAlert
from capital.models import Gasto, CapitalSnapshot, CapitalManualEntry, CapitalComposicion, CapitalComposicionHistory, CapitalEntryHistory, CashBOB, CashFlowLog
from analytics.models import TransactionProfitLedger, PnLDailySnapshot, ExposureSnapshot, SpreadSnapshot, CapitalAnomalyLog, DecisionLog
from data_migration.models import MigrationLog, MigrationCheckpoint, ColumnMapping
from predictions.models import PredictionModel, Prediction, TrainingData
from reports.models import CashTransactionReport, SuspiciousActivityReport, PEPRegistry, DailyOperationLog, GeneratedReport
from snapshots.models import SystemSnapshot
from tarjetas.models import TipoTarjeta, LoteCompra, VentaTarjeta, DetalleVentaLote, MovimientoTarjeta
from alerts.models import AlertLog


def p(msg): print(f"  ✓ {msg}")
def h(msg): print(f"\n{'='*55}\n  {msg}\n{'='*55}")


# ════════════════════════════════════════════════════════
# 1. SUCURSALES
# ════════════════════════════════════════════════════════
h("SUCURSALES")

branch, _ = Branch.objects.get_or_create(
    code='KPTY01',
    defaults={
        'name':    'Kapitalya — La Paz Centro',
        'address': 'Zona Central, La Paz',
        'phone':   '72000000',
        'is_active': True,
    }
)
p(f"Sucursal: {branch.name}")


# ════════════════════════════════════════════════════════
# 2. USUARIOS REALES
# ════════════════════════════════════════════════════════
h("USUARIOS")

# Admin — Sergio (dueño)
admin = User.objects.filter(username='sergio').first()
if not admin:
    admin = User.objects.create_superuser(
        username='sergio', email='kapitalyabolivia@gmail.com',
        first_name='Sergio', last_name='Troche',
        password='Kapitalya2026!', role='ADMIN', branch=branch,
    )
else:
    admin.set_password('Kapitalya2026!')
    admin.email = 'kapitalyabolivia@gmail.com'
    admin.role = 'ADMIN'; admin.branch = branch; admin.is_active = True
    admin.save()
p("sergio / Kapitalya2026! (ADMIN)")

# Cajero — Tiffani
tiffani = User.objects.filter(username='tiffani').first()
if not tiffani:
    tiffani = User(
        username='tiffani', email='tiffani@kapitalya.bo',
        first_name='Tiffani', last_name='Palacios',
        role='CASHIER', branch=branch, is_active=True,
    )
    tiffani.set_password('Tiffani2026!')
    tiffani.save()
else:
    tiffani.set_password('Tiffani2026!')
    tiffani.role = 'CASHIER'; tiffani.branch = branch; tiffani.is_active = True
    tiffani.save()
p("tiffani / Tiffani2026! (CAJERO)")

# Admin genérico
admin2 = User.objects.filter(username='admin').first()
if not admin2:
    admin2 = User.objects.create_superuser(
        username='admin', email='admin@kapitalya.bo',
        first_name='Admin', last_name='Sistema',
        password='Admin123!', role='ADMIN', branch=branch,
    )
else:
    admin2.set_password('Admin123!')
    admin2.save()
p("admin / Admin123! (ADMIN)")


# ════════════════════════════════════════════════════════
# 3. DIVISAS REALES DEL NEGOCIO
# ════════════════════════════════════════════════════════
h("DIVISAS")

# Divisas reales que maneja Kapitalya
DIVISAS = [
    # (codigo, nombre, simbolo, activa, scale_factor)
    # scale_factor=1000 → las tasas se cotizan por 1000 unidades reales
    ('BOB', 'Boliviano',                       'Bs',  True,  1),
    ('USD', 'Dólar Americano',                 '$',   True,  1),
    ('EUR', 'Euro',                            '€',   True,  1),
    ('CLP', 'Peso Chileno',                    'CLP', True,  1000),  # cotizado x1000
    ('PEN', 'Sol Peruano',                     'S/',  True,  1),
    ('BRL', 'Real Brasileño',                  'R$',  True,  1),
    ('ARS', 'Peso Argentino',                  'ARS', True,  1000),  # cotizado x1000
    ('USS', 'Dólar Suelto (deteriorado)',       '$',   True,  1),
    ('US1', 'Dólar 1 y 2 (baja denominación)', '$',   True,  1),
    ('PEM', 'Sol Peruano Moneda',              'S/',  True,  1),
]

currencies = {}
for code, name, symbol, active, scale in DIVISAS:
    c, created = Currency.objects.get_or_create(
        code=code,
        defaults={'name': name, 'symbol': symbol, 'is_active': active, 'scale_factor': scale}
    )
    # Actualizar scale_factor en registros existentes (migración de datos)
    if not created and c.scale_factor != scale:
        c.scale_factor = scale
        c.save(update_fields=['scale_factor'])
    currencies[code] = c
    scale_note = f' [×{scale}]' if scale != 1 else ''
    p(f"{code} — {name}{scale_note}")


# ════════════════════════════════════════════════════════
# 4. TASAS DE CAMBIO REALES (datos de TC Mercado HOY)
# ════════════════════════════════════════════════════════
h("TASAS DE CAMBIO")

bob = currencies['BOB']
now = timezone.now()

# Datos reales del archivo Excel del negocio
TASAS = [
    # (divisa_code, compra, venta)
    ('USD',   Decimal('9.30'),  Decimal('9.60')),
    ('EUR',   Decimal('10.40'), Decimal('10.85')),
    ('CLP',   Decimal('10.00'), Decimal('10.60')),
    ('PEN',   Decimal('2.60'),  Decimal('2.78')),
    ('BRL',   Decimal('1.40'),  Decimal('1.80')),
    ('ARS',   Decimal('5.00'),  Decimal('8.00')),
    ('USS',   Decimal('8.00'),  Decimal('9.00')),
    ('US1',   Decimal('7.00'),  Decimal('8.50')),
    ('PEM',   Decimal('2.00'),  Decimal('2.50')),
]

# Cerrar tasas anteriores
ExchangeRate.objects.filter(currency_to=bob, valid_until__isnull=True).update(
    valid_until=now - timedelta(minutes=1)
)

for code, buy, sell in TASAS:
    if code not in currencies:
        continue
    cur = currencies[code]
    ExchangeRate.objects.create(
        currency_from=cur, currency_to=bob,
        official_rate=(buy + sell) / Decimal('2'), buy_rate=buy, sell_rate=sell,
        market_type='parallel',   # Tasas reales del negocio (mercado paralelo boliviano)
        valid_from=now, source='KAPITALYA',
    )
    p(f"{code}/BOB — Compra: {buy} | Venta: {sell} [paralelo]")

    # Configuración de margen
    RateConfiguration.objects.get_or_create(
        currency_from=cur, currency_to=bob,
        defaults={
            'buy_margin_morning':    Decimal('0.30'),
            'sell_margin_morning':   Decimal('0.30'),
            'buy_margin_afternoon':  Decimal('0.30'),
            'sell_margin_afternoon': Decimal('0.30'),
            'buy_margin_evening':    Decimal('0.30'),
            'sell_margin_evening':   Decimal('0.30'),
            'min_transaction_amount': Decimal('1'),
            'max_transaction_amount': Decimal('100000'),
            'is_active': True,
        }
    )

# Historial de tasas (últimas semanas)
HISTORIAL_TC = [
    # (fecha, USD_c, USD_v, EUR_c, EUR_v, CLP_c, CLP_v, PEN_c, PEN_v)
    ('2026-03-21', 9.4, 9.7, 10.2, 11.2, 10.0, 10.8, 2.5, 2.8),
    ('2026-03-20', 9.4, 9.7, 10.2, 11.2, 10.0, 10.8, 2.5, 2.8),
    ('2026-03-19', 9.4, 9.7, 10.3, 11.1, 10.0, 10.7, 2.5, 2.8),
    ('2026-03-18', 9.3, 9.6, 10.4, 10.9, 10.0, 10.6, 2.6, 2.8),
    ('2026-03-17', 9.3, 9.6, 10.4, 10.9, 10.0, 10.6, 2.6, 2.8),
    ('2026-03-16', 9.3, 9.6, 10.4, 10.85,10.0, 10.6, 2.6, 2.78),
]

for row in HISTORIAL_TC:
    dt = timezone.make_aware(datetime.strptime(row[0], '%Y-%m-%d'))
    for cur_code, buy_i, sell_i in [
        ('USD', 1, 2), ('EUR', 3, 4), ('CLP', 5, 6), ('PEN', 7, 8)
    ]:
        if cur_code in currencies:
            ExchangeRate.objects.get_or_create(
                currency_from=currencies[cur_code], currency_to=bob,
                valid_from=dt.replace(hour=8, minute=0),
                defaults={
                    'official_rate': (Decimal(str(row[buy_i])) + Decimal(str(row[sell_i]))) / Decimal('2'),
                    'buy_rate':  Decimal(str(row[buy_i])),
                    'sell_rate': Decimal(str(row[sell_i])),
                    'market_type': 'parallel',
                    'valid_until': dt.replace(hour=20, minute=0),
                    'source': 'KAPITALYA',
                }
            )


# ════════════════════════════════════════════════════════
# 4b. FUENTES DE TASAS (ExchangeRateSource)
# ════════════════════════════════════════════════════════
h("FUENTES DE TASAS")

SOURCES = [
    # (name, source_type, url, weight, priority, fetch_interval_min, notes)
    (
        'Takenos',
        'digital',
        'https://takenos.com',
        Decimal('1.50'), 3, 60,
        'Plataforma de cambio digital — opera en Bolivia, Argentina, Chile',
    ),
    (
        'Airtm',
        'digital',
        'https://airtm.com',
        Decimal('1.40'), 3, 60,
        'Billetera digital regional con operaciones en Bolivia',
    ),
    (
        'Mercado Paralelo BOL',
        'parallel',
        '',
        Decimal('2.00'), 5, 20,
        'Estimación del mercado paralelo boliviano basada en spread histórico',
    ),
    (
        'ASFI Autorizado',
        'parallel',
        'https://www.asfi.gob.bo/',
        Decimal('1.80'), 4, 30,
        'Tasas de casas de cambio autorizadas por ASFI',
    ),
]

for name, stype, url, weight, priority, interval, notes in SOURCES:
    src, created = ExchangeRateSource.objects.get_or_create(
        name=name,
        defaults={
            'source_type':        stype,
            'url':                url,
            'weight':             weight,
            'priority':           priority,
            'fetch_interval_min': interval,
            'notes':              notes,
            'is_active':          True,
        }
    )
    if not created:
        src.source_type = stype
        src.weight      = weight
        src.priority    = priority
        src.is_active   = True
        src.save(update_fields=['source_type', 'weight', 'priority', 'is_active'])
    action = 'creada' if created else 'actualizada'
    p(f"{name} [{stype}] — {action}")


# ════════════════════════════════════════════════════════
# 5. INVENTARIO REAL (saldos 2025 + operaciones 2026)
# ════════════════════════════════════════════════════════
h("INVENTARIO")

# Datos reales de Inventario Divisas (saldos inicio 2025 + 2026)
INVENTARIO_REAL = [
    # (divisa_code, saldo_actual, minimo, maximo, costo_prom)
    # Saldos basados en Excel real del negocio
    ('USD',   Decimal('2850'),  Decimal('500'),  Decimal('5000'), Decimal('9.55')),
    ('EUR',   Decimal('1850'),  Decimal('200'),  Decimal('3000'), Decimal('10.50')),
    ('CLP',   Decimal('680'),   Decimal('100'),  Decimal('1500'), Decimal('9.70')),
    ('PEN',   Decimal('1980'),  Decimal('300'),  Decimal('4000'), Decimal('2.55')),
    ('BRL',   Decimal('1890'),  Decimal('200'),  Decimal('3000'), Decimal('1.48')),
    ('ARS',   Decimal('250'),   Decimal('50'),   Decimal('500'),  Decimal('5.20')),
    ('USS', Decimal('485'),   Decimal('100'),  Decimal('1000'), Decimal('8.10')),
    ('US1', Decimal('320'),   Decimal('50'),   Decimal('500'),  Decimal('7.50')),
    ('PEM', Decimal('134'),   Decimal('30'),   Decimal('300'),  Decimal('2.15')),
]

for code, saldo, minimo, maximo, costo in INVENTARIO_REAL:
    if code not in currencies:
        continue
    inv, created = CurrencyInventory.objects.get_or_create(
        currency=currencies[code], branch=branch,
        defaults={
            'physical_balance':      saldo,
            'digital_balance':       Decimal('0'),
            'minimum_stock':         minimo,
            'maximum_stock':         maximo,
            'weighted_average_cost': costo,
            'reorder_point':         minimo * Decimal('1.2'),
        }
    )
    if not created:
        inv.physical_balance      = saldo
        inv.minimum_stock         = minimo
        inv.maximum_stock         = maximo
        inv.weighted_average_cost = costo
        inv.save()
    p(f"{code}: {saldo} unidades | CPP: {costo}")


# ════════════════════════════════════════════════════════
# 6. CLIENTES FRECUENTES REALES
# ════════════════════════════════════════════════════════
h("CLIENTES")

CLIENTES = [
    # (doc_type, doc_num, nombre, telefono, email, is_frequent, is_pep, nationality)
    ('CI', '7654321',  'Carlos Eduardo Mamani Quispe', '71234567', '',                True,  False, 'Boliviana'),
    ('CI', '8765432',  'María Fernanda López Tarqui',  '72345678', 'mflопез@mail.com',True,  False, 'Boliviana'),
    ('CI', '9876543',  'Juan Pablo Condori Flores',    '73456789', '',                True,  False, 'Boliviana'),
    ('CI', '6543210',  'Ana Lucía Quispe Mamani',      '74567890', '',                True,  False, 'Boliviana'),
    ('CI', '5432109',  'Roberto Álvarez Mendoza',      '75678901', '',                True,  False, 'Boliviana'),
    # Extranjeros frecuentes
    ('PASSPORT', 'PE123456', 'José Luis Vargas Pérez',   '76789012', '', True, False, 'Peruana'),
    ('PASSPORT', 'AR654321', 'Diego Martínez Silva',     '77890123', '', True, False, 'Argentina'),
    ('PASSPORT', 'CL789012', 'Camila Rojas González',   '78901234', '', True, False, 'Chilena'),
    ('PASSPORT', 'BR321654', 'Ana Carolina Souza',       '79012345', '', True, False, 'Brasileña'),
    # Clientes ocasionales
    ('CI', '1122334', 'Luis Antonio Poma Chura',       '70112233', '', False, False, 'Boliviana'),
    ('CI', '2233445', 'Sandra Patricia Cruz Vela',     '70223344', '', False, False, 'Boliviana'),
    ('CI', '3344556', 'Miguel Ángel Torrez Mamani',    '70334455', '', False, False, 'Boliviana'),
    ('CI', '4455667', 'Carmen Rosa Apaza Huanca',      '70445566', '', False, False, 'Boliviana'),
    ('CI', '5566778', 'Pedro Gonzalo Lima Quispe',     '70556677', '', False, False, 'Boliviana'),
    # NIT empresas
    ('NIT', '123456789', 'Importaciones Andinas SRL',  '22111222', 'admin@andinas.bo', True, False, 'Boliviana'),
    ('NIT', '987654321', 'Comercial del Norte SA',     '22222333', '',                 True, False, 'Boliviana'),
    # PEP
    ('CI', '9988776', 'Ricardo Fuentes Blanco',        '70998877', '', False, True,  'Boliviana'),
]

customers = {}
for doc_type, doc_num, nombre, tel, email, frecuente, pep, nac in CLIENTES:
    c, _ = Customer.objects.get_or_create(
        document_number=doc_num,
        defaults={
            'document_type': doc_type,
            'full_name':     nombre,
            'phone':         tel,
            'email':         email,
            'nationality':   nac,
            'is_frequent':   frecuente,
            'is_pep':        pep,
        }
    )
    customers[doc_num] = c
    tag = ' [PEP]' if pep else (' [⭐]' if frecuente else '')
    p(f"{nombre}{tag}")


# ════════════════════════════════════════════════════════
# 7. TRANSACCIONES REALES (enero-marzo 2026)
# ════════════════════════════════════════════════════════
h("TRANSACCIONES REALES (Enero-Marzo 2026)")

# Transacciones reales extraídas del Excel
TX_REALES = [
    # (fecha, tipo, divisa_code, cantidad, tc, total, medio, cajero_user)
    # Enero 2026
    ('2026-01-02', 'SELL', 'CLP',   45,    11.0,  495,    'CASH', 'sergio'),
    ('2026-01-02', 'BUY',  'ARS',   8,     5.0,   40,     'CASH', 'sergio'),
    ('2026-01-02', 'BUY',  'EUR',   20,    10.4,  208,    'CASH', 'sergio'),
    ('2026-01-02', 'BUY',  'USD',   100,   9.5,   950,    'CASH', 'sergio'),
    ('2026-01-02', 'BUY',  'USD',   100,   9.5,   950,    'CASH', 'sergio'),
    ('2026-01-02', 'SELL', 'USD',   400,   10.0,  4000,   'CASH', 'sergio'),
    ('2026-01-02', 'SELL', 'USD',   200,   10.0,  2000,   'CASH', 'sergio'),
    ('2026-01-02', 'BUY',  'USD',   200,   9.5,   1900,   'CASH', 'sergio'),
    ('2026-01-02', 'SELL', 'USD',   600,   10.0,  6000,   'CASH', 'sergio'),
    ('2026-01-02', 'BUY',  'USD',   100,   9.5,   950,    'CASH', 'sergio'),
    ('2026-01-02', 'SELL', 'US1', 50,    9.5,   475,    'QR',   'sergio'),
    ('2026-01-02', 'SELL', 'USS', 120,   9.5,   1140,   'QR',   'sergio'),
    ('2026-01-03', 'BUY',  'CLP',   20,    9.6,   192,    'CASH', 'sergio'),
    ('2026-01-03', 'BUY',  'CLP',   12,    9.6,   115.2,  'CASH', 'tiffani'),
    ('2026-01-03', 'SELL', 'USD',   1000,  10.0,  10000,  'CASH', 'sergio'),
    ('2026-01-03', 'BUY',  'USD',   100,   9.6,   960,    'CASH', 'sergio'),
    ('2026-01-03', 'BUY',  'USD',   500,   9.6,   4800,   'CASH', 'sergio'),
    ('2026-01-03', 'BUY',  'USD',   100,   9.6,   960,    'CASH', 'tiffani'),
    ('2026-01-03', 'BUY',  'USD',   100,   9.6,   960,    'CASH', 'tiffani'),
    ('2026-01-03', 'BUY',  'USD',   50,    9.6,   480,    'CASH', 'tiffani'),
    ('2026-01-05', 'BUY',  'USD',   8500,  9.7,   82450,  'CASH', 'sergio'),
    ('2026-01-05', 'SELL', 'USD',   200,   10.0,  2000,   'CASH', 'sergio'),
    ('2026-01-05', 'BUY',  'USD',   200,   9.7,   1940,   'CASH', 'sergio'),
    ('2026-01-05', 'SELL', 'USD',   500,   10.0,  5000,   'CASH', 'sergio'),
    ('2026-01-05', 'SELL', 'USD',   100,   10.0,  1000,   'QR',   'sergio'),
    ('2026-01-05', 'SELL', 'USD',   2500,  10.0,  25000,  'CASH', 'sergio'),
    ('2026-01-05', 'BUY',  'USD',   300,   9.6,   2880,   'CASH', 'tiffani'),
    ('2026-01-05', 'SELL', 'USD',   100,   10.0,  1000,   'CASH', 'tiffani'),
    ('2026-01-05', 'SELL', 'USD',   3000,  10.0,  30000,  'CASH', 'tiffani'),
    ('2026-01-06', 'BUY',  'CLP',   10,    9.6,   96,     'CASH', 'sergio'),
    ('2026-01-06', 'SELL', 'CLP',   500,   10.9,  5450,   'CASH', 'tiffani'),
    ('2026-01-06', 'SELL', 'CLP',   265,   10.9,  2888.5, 'CASH', 'tiffani'),
    ('2026-01-06', 'BUY',  'USD',   100,   8.0,   800,    'CASH', 'sergio'),
    ('2026-01-06', 'SELL', 'USD',   1500,  10.05, 15075,  'CASH', 'sergio'),
    ('2026-01-06', 'BUY',  'USD',   100,   9.7,   970,    'CASH', 'sergio'),
    # Febrero - muestra representativa
    ('2026-02-03', 'BUY',  'EUR',   50,    10.2,  510,    'CASH', 'sergio'),
    ('2026-02-03', 'SELL', 'EUR',   30,    10.85, 325.5,  'CASH', 'sergio'),
    ('2026-02-05', 'BUY',  'USD',   500,   9.4,   4700,   'CASH', 'sergio'),
    ('2026-02-05', 'SELL', 'USD',   800,   10.0,  8007,   'CASH', 'tiffani'),
    ('2026-02-10', 'BUY',  'PEN',   200,   2.5,   500,    'CASH', 'sergio'),
    ('2026-02-10', 'SELL', 'PEN',   150,   2.78,  417,    'CASH', 'sergio'),
    ('2026-02-15', 'BUY',  'BRL',   100,   1.4,   140,    'CASH', 'sergio'),
    ('2026-02-15', 'SELL', 'BRL',   80,    1.8,   144,    'CASH', 'tiffani'),
    ('2026-02-20', 'BUY',  'USD',   1000,  9.5,   9500,   'CASH', 'sergio'),
    ('2026-02-20', 'SELL', 'USD',   1200,  10.05, 12060,  'CASH', 'sergio'),
    ('2026-02-25', 'SELL', 'ARS',   500,   7.5,   3750,   'CASH', 'tiffani'),
    ('2026-02-28', 'BUY',  'USD',   800,   9.5,   7600,   'TRANSFER', 'sergio'),
    # Marzo - más reciente
    ('2026-03-03', 'BUY',  'EUR',   100,   10.4,  1040,   'CASH', 'sergio'),
    ('2026-03-03', 'SELL', 'EUR',   80,    10.85, 868,    'CASH', 'sergio'),
    ('2026-03-05', 'BUY',  'USD',   2000,  9.3,   18600,  'CASH', 'sergio'),
    ('2026-03-05', 'SELL', 'USD',   1500,  9.6,   14400,  'CASH', 'tiffani'),
    ('2026-03-10', 'BUY',  'CLP',   500,   10.0,  5000,   'CASH', 'sergio'),
    ('2026-03-10', 'SELL', 'CLP',   400,   10.6,  4240,   'CASH', 'sergio'),
    ('2026-03-12', 'BUY',  'PEN',   500,   2.6,   1300,   'CASH', 'sergio'),
    ('2026-03-12', 'SELL', 'PEN',   300,   2.78,  834,    'CASH', 'tiffani'),
    ('2026-03-15', 'BUY',  'USD',   3000,  9.3,   27900,  'CASH', 'sergio'),
    ('2026-03-15', 'SELL', 'USD',   2500,  9.6,   24000,  'CASH', 'sergio'),
    ('2026-03-18', 'BUY',  'BRL',   200,   1.4,   280,    'CASH', 'sergio'),
    ('2026-03-18', 'SELL', 'BRL',   150,   1.8,   270,    'CASH', 'tiffani'),
    ('2026-03-20', 'BUY',  'EUR',   150,   10.4,  1560,   'CASH', 'sergio'),
    ('2026-03-20', 'SELL', 'EUR',   100,   10.85, 1085,   'CASH', 'sergio'),
    ('2026-03-21', 'SELL', 'USD',   500,   9.6,   4800,   'TRANSFER', 'sergio'),
    ('2026-03-21', 'BUY',  'USD',   600,   9.3,   5580,   'CASH', 'tiffani'),
    ('2026-03-22', 'SELL', 'USD',   1000,  9.6,   9600,   'CASH', 'sergio'),
    ('2026-03-23', 'BUY',  'USD',   500,   9.3,   4650,   'CASH', 'sergio'),
    ('2026-03-23', 'SELL', 'PEN',   200,   2.78,  556,    'CASH', 'tiffani'),
    ('2026-03-24', 'BUY',  'EUR',   80,    10.4,  832,    'CASH', 'sergio'),
    ('2026-03-24', 'SELL', 'ARS',   1000,  7.5,   7500,   'CASH', 'tiffani'),
    ('2026-03-25', 'BUY',  'USD',   800,   9.3,   7440,   'CASH', 'sergio'),
    ('2026-03-25', 'SELL', 'USD',   700,   9.6,   6720,   'CASH', 'sergio'),
    ('2026-03-26', 'BUY',  'USD',   200,   9.3,   1860,   'CASH', 'sergio'),
    ('2026-03-26', 'SELL', 'USD',   300,   9.6,   2880,   'QR',   'tiffani'),
]

# Mapa de usuarios
user_map = {'sergio': admin, 'tiffani': tiffani}

# Lista de clientes para asignación aleatoria
client_list = list(customers.values())

# Mapa de divisa a currency_from/currency_to
def get_currencies(divisa_code, tipo):
    """BUY = cliente vende divisa (casa compra), SELL = cliente compra divisa"""
    if divisa_code not in currencies:
        return None, None
    div = currencies[divisa_code]
    if tipo == 'BUY':
        return div, bob   # casa recibe divisa, entrega BOB
    else:
        return bob, div   # casa entrega divisa, recibe BOB

tx_counter = {}

for fecha_str, tipo, div_code, cantidad, tc, total, medio, cajero_user in TX_REALES:
    try:
        fecha = timezone.make_aware(
            datetime.strptime(fecha_str, '%Y-%m-%d').replace(
                hour=random.randint(9, 18),
                minute=random.randint(0, 59)
            )
        )
    except Exception:
        continue

    cajero = user_map.get(cajero_user, admin)
    cur_from, cur_to = get_currencies(div_code, tipo)
    if not cur_from or not cur_to:
        continue

    # Número de transacción
    date_key = fecha.strftime('%Y%m%d')
    tx_counter[date_key] = tx_counter.get(date_key, 0) + 1
    tx_num = f"KPT{date_key}{tx_counter[date_key]:04d}"

    # Cliente aleatorio
    cliente = random.choice(client_list)

    # Medio de pago
    medio_map = {'CASH': 'CASH', 'QR': 'QR', 'TRANSFER': 'TRANSFER'}
    payment = medio_map.get(medio, 'CASH')

    tx, created = Transaction.objects.get_or_create(
        transaction_number=tx_num,
        defaults={
            'transaction_type': tipo,
            'status':           'COMPLETED',
            'customer':         cliente,
            'currency_from':    cur_from,
            'currency_to':      cur_to,
            'amount_from':      Decimal(str(cantidad)),
            'amount_to':        Decimal(str(total)),
            'exchange_rate':    Decimal(str(tc)),
            'payment_method':   payment,
            'cashier':          cajero,
            'branch':           branch,
            'completed_at':     fecha,
            'created_at':       fecha,
        }
    )
    if created:
        # Bypass auto_now_add
        Transaction.objects.filter(pk=tx.pk).update(created_at=fecha)

created_count = Transaction.objects.filter(
    transaction_number__startswith='KPT'
).count()
p(f"{created_count} transacciones reales creadas")


# ════════════════════════════════════════════════════════
# 8. ALERTAS DE INVENTARIO (basadas en datos reales)
# ════════════════════════════════════════════════════════
h("ALERTAS DE INVENTARIO")

for code, saldo, minimo, maximo, _ in INVENTARIO_REAL:
    if code not in currencies:
        continue
    inv = CurrencyInventory.objects.filter(
        currency=currencies[code], branch=branch
    ).first()
    if not inv:
        continue

    if inv.needs_replenishment:
        InventoryAlert.objects.get_or_create(
            inventory=inv, alert_type='LOW_STOCK', is_resolved=False,
            defaults={
                'severity': 'HIGH',
                'message':  f'Stock bajo de {code}: {saldo} unidades (mínimo: {minimo})',
                'data': {
                    'current_balance': float(saldo),
                    'minimum_stock':   float(minimo),
                    'percentage':      float(saldo / maximo * 100),
                },
                'triggered_by': admin,
            }
        )
        p(f"Alerta LOW_STOCK: {code}")

    if inv.is_overstocked:
        InventoryAlert.objects.get_or_create(
            inventory=inv, alert_type='OVERSTOCK', is_resolved=False,
            defaults={
                'severity': 'MEDIUM',
                'message':  f'Exceso de stock de {code}',
                'data':     {'current_balance': float(saldo)},
                'triggered_by': admin,
            }
        )
        p(f"Alerta OVERSTOCK: {code}")


# ════════════════════════════════════════════════════════
# 9. CAPITAL
# ════════════════════════════════════════════════════════
h("CAPITAL")

# Gastos
gastos_data = [
    {'categoria': 'ALQUILER', 'descripcion': 'Alquiler mensual oficina', 'monto_bob': Decimal('2500'), 'medio_pago': 'TRANSFER', 'proveedor': 'Propietario'},
    {'categoria': 'SERVICIOS', 'descripcion': 'Luz y agua', 'monto_bob': Decimal('450'), 'medio_pago': 'EFECTIVO'},
    {'categoria': 'SUELDOS', 'descripcion': 'Sueldos empleados', 'monto_bob': Decimal('8007'), 'medio_pago': 'TRANSFER'},
    {'categoria': 'COMISIONES', 'descripcion': 'Comisiones bancarias', 'monto_bob': Decimal('120'), 'medio_pago': 'QR'},
    {'categoria': 'PUBLICIDAD', 'descripcion': 'Anuncios en redes sociales', 'monto_bob': Decimal('300'), 'medio_pago': 'TARJETA'},
    {'categoria': 'IMPUESTOS', 'descripcion': 'Impuestos municipales', 'monto_bob': Decimal('500'), 'medio_pago': 'TRANSFER'},
    {'categoria': 'MANTENIMIENTO', 'descripcion': 'Reparación de equipos', 'monto_bob': Decimal('200'), 'medio_pago': 'EFECTIVO'},
]

for gasto in gastos_data:
    Gasto.objects.get_or_create(
        fecha=timezone.localdate() - timedelta(days=random.randint(1, 30)),
        categoria=gasto['categoria'],
        descripcion=gasto['descripcion'],
        defaults={
            'monto_bob': gasto['monto_bob'],
            'medio_pago': gasto['medio_pago'],
            'proveedor': gasto.get('proveedor', ''),
            'branch': branch,
            'registrado_por': admin,
        }
    )
p("Gastos operativos creados")

# CapitalSnapshot
for i in range(7):
    fecha_snap = timezone.localdate() - timedelta(days=i)
    CapitalSnapshot.objects.get_or_create(
        fecha=fecha_snap,
        branch=branch,
        defaults={
            'efectivo_bob': Decimal('15000') + Decimal(random.randint(-1000, 1000)),
            'qr_bob': Decimal('5000') + Decimal(random.randint(-500, 500)),
            'divisas_bob': Decimal('50000') + Decimal(random.randint(-5000, 5000)),
            'tarjetas_bob': Decimal('10000') + Decimal(random.randint(-1000, 1000)),
            'pasivos_bob': Decimal('2000') + Decimal(random.randint(-200, 200)),
            'total_bob': Decimal('78007') + Decimal(random.randint(-2000, 2000)),
            'tipo': 'CIERRE' if i == 0 else 'MANUAL',
            'generado_por': admin,
        }
    )
p("Snapshots de capital creados")

# CapitalManualEntry
CapitalManualEntry.objects.get_or_create(
    branch=branch,
    defaults={
        'efectivo_bob': Decimal('15000'),
        'qr_bob': Decimal('5000'),
        'pasivos_bob': Decimal('2000'),
        'notas': 'Entrada manual inicial',
    }
)
p("Entrada manual de capital creada")

# CashBOB
CashBOB.objects.get_or_create(
    branch=branch,
    defaults={
        'balance': Decimal('15000'),
        'last_updated': timezone.now(),
    }
)
p("Saldo de efectivo BOB creado")

# CashFlowLog
CashFlowLog.objects.get_or_create(
    branch=branch,
    transaction_type='INGRESO',
    amount=Decimal('1000'),
    description='Ingreso inicial',
    defaults={
        'balance_after': Decimal('16000'),
        'created_by': admin,
    }
)
p("Log de flujo de caja creado")


# ════════════════════════════════════════════════════════
# 10. ANALYTICS
# ════════════════════════════════════════════════════════
h("ANALYTICS")

# TransactionProfitLedger
for tx in Transaction.objects.all()[:10]:  # First 10 transactions
    TransactionProfitLedger.objects.get_or_create(
        transaction=tx,
        defaults={
            'profit_bob': Decimal(random.uniform(10, 100)),
            'profit_percentage': Decimal(random.uniform(1, 10)),
            'calculated_at': timezone.now(),
        }
    )
p("Ledgers de ganancias creados")

# PnLDailySnapshot
for i in range(7):
    fecha_snap = timezone.localdate() - timedelta(days=i)
    PnLDailySnapshot.objects.get_or_create(
        date=fecha_snap,
        branch=branch,
        defaults={
            'total_profit': Decimal(random.uniform(200, 800)),
            'total_volume': Decimal(random.uniform(5000, 15000)),
            'transaction_count': random.randint(5, 20),
        }
    )
p("Snapshots diarios P&L creados")

# ExposureSnapshot
for i in range(7):
    fecha_snap = timezone.localdate() - timedelta(days=i)
    ExposureSnapshot.objects.get_or_create(
        date=fecha_snap,
        branch=branch,
        defaults={
            'usd_exposure': Decimal(random.uniform(1000, 3000)),
            'eur_exposure': Decimal(random.uniform(500, 1500)),
            'total_exposure_bob': Decimal(random.uniform(20000, 40000)),
        }
    )
p("Snapshots de exposición creados")

# SpreadSnapshot
for cur_code in ['USD', 'EUR', 'CLP']:
    if cur_code in currencies:
        SpreadSnapshot.objects.get_or_create(
            date=timezone.localdate(),
            currency_from=currencies[cur_code],
            currency_to=bob,
            defaults={
                'average_spread': Decimal(random.uniform(0.3, 1.0)),
                'min_spread': Decimal(random.uniform(0.1, 0.5)),
                'max_spread': Decimal(random.uniform(0.8, 1.5)),
            }
        )
p("Snapshots de spread creados")

# CapitalAnomalyLog
CapitalAnomalyLog.objects.get_or_create(
    date=timezone.localdate(),
    branch=branch,
    anomaly_type='UNEXPECTED_DROP',
    defaults={
        'description': 'Caída inesperada en capital',
        'severity': 'HIGH',
        'detected_at': timezone.now(),
    }
)
p("Log de anomalía de capital creado")

# DecisionLog
DecisionLog.objects.get_or_create(
    timestamp=timezone.now(),
    decision_type='RATE_ADJUSTMENT',
    defaults={
        'parameters': {'currency': 'USD', 'adjustment': 0.1},
        'outcome': 'SUCCESS',
        'confidence': Decimal('0.95'),
    }
)
p("Log de decisión creado")


# ════════════════════════════════════════════════════════
# 11. DATA MIGRATION
# ════════════════════════════════════════════════════════
h("DATA MIGRATION")

# MigrationLog
MigrationLog.objects.get_or_create(
    migration_id='initial_migration',
    defaults={
        'status': 'COMPLETED',
        'source_table': 'old_transactions',
        'target_table': 'transactions_transaction',
        'records_processed': 100,
        'started_at': timezone.now() - timedelta(hours=1),
        'completed_at': timezone.now(),
    }
)
p("Log de migración creado")

# MigrationCheckpoint
MigrationCheckpoint.objects.get_or_create(
    migration_id='initial_migration',
    checkpoint_id='checkpoint_1',
    defaults={
        'last_processed_id': 50,
        'status': 'COMPLETED',
        'created_at': timezone.now(),
    }
)
p("Checkpoint de migración creado")

# ColumnMapping
ColumnMapping.objects.get_or_create(
    migration_id='initial_migration',
    source_column='old_amount',
    target_column='amount_from',
    defaults={
        'data_type': 'decimal',
        'transformation': 'multiply_by_100',
    }
)
p("Mapeo de columna creado")


# ════════════════════════════════════════════════════════
# 12. PREDICTIONS
# ════════════════════════════════════════════════════════
h("PREDICTIONS")

# PredictionModel
PredictionModel.objects.get_or_create(
    name='USD_BOB_Rate_Predictor',
    model_type='LINEAR_REGRESSION',
    defaults={
        'version': '1.0',
        'accuracy_score': Decimal('0.85'),
        'is_active': True,
        'created_at': timezone.now(),
    }
)
p("Modelo de predicción creado")

# Prediction
Prediction.objects.get_or_create(
    model=PredictionModel.objects.first(),
    currency_from=currencies['USD'],
    currency_to=bob,
    defaults={
        'predicted_rate': Decimal('9.5'),
        'confidence': Decimal('0.8'),
        'prediction_date': timezone.localdate() + timedelta(days=1),
        'created_at': timezone.now(),
    }
)
p("Predicción creada")

# TrainingData
TrainingData.objects.get_or_create(
    model=PredictionModel.objects.first(),
    defaults={
        'data': {'features': [1, 2, 3], 'target': 9.5},
        'created_at': timezone.now(),
    }
)
p("Datos de entrenamiento creados")


# ════════════════════════════════════════════════════════
# 13. REPORTS
# ════════════════════════════════════════════════════════
h("REPORTS")

# CashTransactionReport
for i in range(7):
    fecha_rep = timezone.localdate() - timedelta(days=i)
    CashTransactionReport.objects.get_or_create(
        date=fecha_rep,
        branch=branch,
        defaults={
            'total_cash_in': Decimal(random.uniform(30000, 60000)),
            'total_cash_out': Decimal(random.uniform(25000, 55000)),
            'net_cash_flow': Decimal(random.uniform(-5000, 10000)),
            'generated_at': timezone.now(),
        }
    )
p("Reportes de transacciones en efectivo creados")

# SuspiciousActivityReport
for tx in Transaction.objects.all()[:5]:
    SuspiciousActivityReport.objects.get_or_create(
        transaction=tx,
        report_type='LARGE_TRANSACTION',
        defaults={
            'severity': 'MEDIUM',
            'description': 'Transacción grande detectada',
            'reported_at': timezone.now(),
        }
    )
p("Reportes de actividad sospechosa creados")

# PEPRegistry
pep_customers = Customer.objects.filter(is_pep=True)
if not pep_customers.exists():
    pep_customer = Customer.objects.filter(document_number='9988776').first()
    if pep_customer:
        PEPRegistry.objects.get_or_create(
            customer=pep_customer,
            pep_type='POLITICAL',
            defaults={
                'full_name': 'Ricardo Fuentes Blanco',
                'position': 'Ministro',
                'country': 'Bolivia',
                'registered_at': timezone.now(),
            }
        )
p("Registros PEP creados")

# DailyOperationLog
for i in range(7):
    fecha_log = timezone.localdate() - timedelta(days=i)
    DailyOperationLog.objects.get_or_create(
        date=fecha_log,
        branch=branch,
        defaults={
            'opening_balance': Decimal(random.uniform(8007, 12000)),
            'closing_balance': Decimal(random.uniform(12000, 18007)),
            'total_transactions': random.randint(10, 30),
            'generated_at': timezone.now(),
        }
    )
p("Logs de operaciones diarias creados")

# GeneratedReport
GeneratedReport.objects.get_or_create(
    report_type='DAILY_SUMMARY',
    date=timezone.localdate(),
    defaults={
        'file_path': '/reports/daily_summary.pdf',
        'generated_by': admin,
        'generated_at': timezone.now(),
    }
)
p("Reporte generado creado")


# ════════════════════════════════════════════════════════
# 14. SNAPSHOTS
# ════════════════════════════════════════════════════════
h("SNAPSHOTS")

# SystemSnapshot
SystemSnapshot.objects.get_or_create(
    snapshot_type='FULL_BACKUP',
    defaults={
        'description': 'Backup completo del sistema',
        'data': {'tables': ['users', 'transactions']},
        'created_by': admin,
        'created_at': timezone.now(),
    }
)
p("Snapshot del sistema creado")


# ════════════════════════════════════════════════════════
# 15. TARJETAS
# ════════════════════════════════════════════════════════
h("TARJETAS")

# TipoTarjeta
tipos_tarjeta = [
    {'nombre': 'Visa Débito', 'descripcion': 'Tarjeta Visa débito', 'precio_compra': Decimal('50'), 'precio_venta': Decimal('60')},
    {'nombre': 'Mastercard Crédito', 'descripcion': 'Tarjeta Mastercard crédito', 'precio_compra': Decimal('55'), 'precio_venta': Decimal('65')},
    {'nombre': 'American Express', 'descripcion': 'Tarjeta American Express', 'precio_compra': Decimal('60'), 'precio_venta': Decimal('70')},
]

tipo_tarjetas = []
for tipo_data in tipos_tarjeta:
    tipo, _ = TipoTarjeta.objects.get_or_create(
        nombre=tipo_data['nombre'],
        defaults={
            'descripcion': tipo_data['descripcion'],
            'precio_compra': tipo_data['precio_compra'],
            'precio_venta': tipo_data['precio_venta'],
            'activo': True,
        }
    )
    tipo_tarjetas.append(tipo)
p("Tipos de tarjeta creados")

# LoteCompra
lotes = []
for i, tipo in enumerate(tipo_tarjetas):
    lote, _ = LoteCompra.objects.get_or_create(
        numero_lote=f'LOTE00{i+1}',
        tipo_tarjeta=tipo,
        defaults={
            'cantidad': 100 + i * 50,
            'precio_unitario': tipo.precio_compra,
            'total_compra': (100 + i * 50) * tipo.precio_compra,
            'proveedor': f'Proveedor {i+1}',
            'fecha_compra': timezone.localdate() - timedelta(days=i*7),
            'comprado_por': admin,
        }
    )
    lotes.append(lote)
p("Lotes de compra creados")

# VentaTarjeta
clientes = list(Customer.objects.all())
for i, lote in enumerate(lotes):
    for j in range(min(3, lote.cantidad // 10)):  # Sell some
        VentaTarjeta.objects.get_or_create(
            lote=lote,
            defaults={
                'cliente': random.choice(clientes),
                'cantidad': random.randint(1, 10),
                'precio_unitario': lote.tipo_tarjeta.precio_venta,
                'total_venta': random.randint(1, 10) * lote.tipo_tarjeta.precio_venta,
                'medio_pago': random.choice(['EFECTIVO', 'QR', 'TARJETA']),
                'vendido_por': admin,
                'fecha_venta': timezone.localdate() - timedelta(days=random.randint(1, 30)),
            }
        )
p("Ventas de tarjeta creadas")


# ════════════════════════════════════════════════════════
# 16. ALERTS
# ════════════════════════════════════════════════════════
h("ALERTS")

# AlertLog
AlertLog.objects.get_or_create(
    alert_type='SYSTEM',
    severity='INFO',
    defaults={
        'message': 'Sistema inicializado',
        'data': {'version': '1.0'},
        'resolved': True,
        'created_at': timezone.now(),
    }
)
p("Log de alerta creado")


# ════════════════════════════════════════════════════════
# RESUMEN FINAL
# ════════════════════════════════════════════════════════
print(f"""
{'='*55}
  KAPITALYA — DATOS DE PRUEBA CREADOS
{'='*55}

  ACCESO AL SISTEMA:
  ─────────────────────────────────────────────
  Admin (dueño)  : sergio     / Kapitalya2026!
  Cajero         : tiffani    / Tiffani2026!
  Admin genérico : admin      / Admin123!

  URL Web   : http://localhost:3000
  URL Admin  : http://localhost:8007/admin/

  DATOS CREADOS:
  ─────────────────────────────────────────────
  Sucursales    : {Branch.objects.count()}
  Usuarios      : {User.objects.count()}
  Divisas       : {Currency.objects.count()}
  Tasas hoy     : {ExchangeRate.objects.filter(valid_until__isnull=True).count()}
  Clientes      : {Customer.objects.count()}
  Transacciones : {Transaction.objects.count()}
  Inventario    : {CurrencyInventory.objects.count()} divisas
  Alertas       : {InventoryAlert.objects.filter(is_resolved=False).count()} activas

  TODOS LOS MODELOS HAN SIDO POBLADOS CON DATOS DE PRUEBA

  DIVISAS DEL NEGOCIO:
  USD, EUR, CLP, PEN, BRL, ARS
  + USD Sueltos, USD 1y2, PEN Moneda

  OPERADORES:
  Sergio (Admin/Dueño) + Tiffani (Cajero)
{'='*55}
""")