"""
Script para poblar la base de datos con datos de prueba.
Uso: python manage.py shell < scripts/seed_data.py
  o: python manage.py runscript seed_data  (con django-extensions)
"""
import os
import django
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.development')
django.setup()

from decimal import Decimal
from django.utils import timezone
from users.models import User, Branch
from rates.models import Currency, ExchangeRate, RateConfiguration

print('Creando sucursales...')
branch_main = Branch.objects.get_or_create(
    code='SUC01',
    defaults={
        'name':    'Sucursal Central',
        'address': 'Av. Mariscal Santa Cruz 123, La Paz',
        'phone':   '2-2345678',
        'is_active': True,
    }
)[0]

branch_2 = Branch.objects.get_or_create(
    code='SUC02',
    defaults={
        'name':    'Sucursal San Miguel',
        'address': 'Calle 21 de Calacoto 456, La Paz',
        'phone':   '2-2789012',
        'is_active': True,
    }
)[0]
print(f'  ✓ {branch_main.name}')
print(f'  ✓ {branch_2.name}')

print('Creando usuarios...')
# Admin
admin = User.objects.filter(username='admin').first()
if not admin:
    admin = User.objects.create_superuser(
        username='admin',
        password='Admin123!',
        email='admin@forexerp.com',
        first_name='Administrador',
        last_name='Sistema',
        role='ADMIN',
        branch=branch_main,
    )
    print('  ✓ admin / Admin123!')
else:
    admin.set_password('Admin123!')
    admin.role = 'ADMIN'
    admin.branch = branch_main
    admin.is_active = True
    admin.save()
    print('  ✓ admin actualizado / Admin123!')

# Supervisor
supervisor, created = User.objects.get_or_create(
    username='supervisor',
    defaults={
        'email':      'supervisor@forexerp.com',
        'first_name': 'Carlos',
        'last_name':  'Mendoza',
        'role':       'SUPERVISOR',
        'branch':     branch_main,
        'is_active':  True,
    }
)
supervisor.set_password('Super123!')
supervisor.save()
print(f'  ✓ supervisor / Super123!')

# Cajero
cashier, created = User.objects.get_or_create(
    username='cajero',
    defaults={
        'email':      'cajero@forexerp.com',
        'first_name': 'Maria',
        'last_name':  'Lopez',
        'role':       'CASHIER',
        'branch':     branch_main,
        'is_active':  True,
    }
)
cashier.set_password('Cajero123!')
cashier.save()
print(f'  ✓ cajero / Cajero123!')

print('Creando divisas...')
currencies_data = [
    ('USD', 'Dólar Estadounidense', '$',  True),
    ('EUR', 'Euro',                 '€',  True),
    ('BOB', 'Boliviano',            'Bs', True),
    ('BRL', 'Real Brasileño',       'R$', True),
    ('ARS', 'Peso Argentino',       '$',  True),
    ('CLP', 'Peso Chileno',         '$',  True),
    ('PEN', 'Sol Peruano',          'S/', True),
]
currencies = {}
for code, name, symbol, active in currencies_data:
    c, _ = Currency.objects.get_or_create(
        code=code,
        defaults={'name': name, 'symbol': symbol, 'is_active': active}
    )
    currencies[code] = c
    print(f'  ✓ {code} - {name}')

print('Creando tasas de cambio...')
bob = currencies['BOB']
rates_data = [
    ('USD', Decimal('6.96'),  Decimal('6.93'),  Decimal('6.99')),
    ('EUR', Decimal('7.55'),  Decimal('7.50'),  Decimal('7.60')),
    ('BRL', Decimal('1.22'),  Decimal('1.20'),  Decimal('1.24')),
    ('ARS', Decimal('0.007'), Decimal('0.006'), Decimal('0.008')),
    ('CLP', Decimal('0.007'), Decimal('0.006'), Decimal('0.008')),
    ('PEN', Decimal('1.85'),  Decimal('1.83'),  Decimal('1.87')),
]
for code, official, buy, sell in rates_data:
    cur = currencies[code]
    ExchangeRate.objects.get_or_create(
        currency_from=cur,
        currency_to=bob,
        valid_from=timezone.now().replace(hour=0, minute=0, second=0, microsecond=0),
        defaults={
            'official_rate': official,
            'buy_rate':      buy,
            'sell_rate':     sell,
            'source':        'BCB',
        }
    )
    print(f'  ✓ {code}/BOB — compra: {buy} / venta: {sell}')

print('Creando configuraciones de tasas...')
for code, official, buy, sell in rates_data:
    cur = currencies[code]
    margin = Decimal('0.50')
    RateConfiguration.objects.get_or_create(
        currency_from=cur,
        currency_to=bob,
        defaults={
            'buy_margin_morning':    margin,
            'sell_margin_morning':   margin,
            'buy_margin_afternoon':  margin,
            'sell_margin_afternoon': margin,
            'buy_margin_evening':    margin,
            'sell_margin_evening':   margin,
            'min_transaction_amount': Decimal('10'),
            'max_transaction_amount': Decimal('50000'),
            'is_active': True,
        }
    )
    print(f'  ✓ Config {code}/BOB')

print('Creando clientes de prueba...')
from transactions.models import Customer
customers_data = [
    ('CI',       '1234567',   'Juan Carlos Pérez López',   '71234567', 'juan@email.com',  False),
    ('CI',       '2345678',   'María Elena García',         '72345678', 'maria@email.com', False),
    ('PASSPORT', 'US123456',  'John Smith',                 '71111111', 'john@email.com',  False),
    ('NIT',      '12345678',  'Empresa Importadora SRL',    '22222222', 'emp@email.com',   False),
    ('CI',       '9876543',   'Carlos Mendoza Quispe',      '73456789', '',                True),
]
for doc_type, doc_num, name, phone, email, is_pep in customers_data:
    Customer.objects.get_or_create(
        document_number=doc_num,
        defaults={
            'document_type': doc_type,
            'full_name':     name,
            'phone':         phone,
            'email':         email,
            'nationality':   'Boliviana',
            'is_pep':        is_pep,
            'is_frequent':   False,
        }
    )
    print(f'  ✓ {name}')

print('Creando transacciones de prueba...')
from transactions.models import Transaction
import random

customers    = list(Customer.objects.all())
usd          = currencies['USD']
eur          = currencies['EUR']
from datetime import timedelta
from django.utils import timezone as tz

for i in range(10):
    tx_type  = random.choice(['BUY', 'SELL'])
    currency = random.choice([usd, eur])
    rate     = Decimal('6.96') if currency == usd else Decimal('7.55')
    amount   = Decimal(str(random.randint(100, 2000)))
    customer = random.choice(customers)

    Transaction.objects.get_or_create(
        transaction_number=f'SUC01{tz.now().strftime("%Y%m%d")}{i+1:04d}',
        defaults={
            'transaction_type': tx_type,
            'status':           'COMPLETED',
            'customer':         customer,
            'currency_from':    currency if tx_type == 'BUY'  else bob,
            'currency_to':      bob      if tx_type == 'BUY'  else currency,
            'amount_from':      amount,
            'amount_to':        amount * rate if tx_type == 'BUY' else amount / rate,
            'exchange_rate':    rate,
            'payment_method':   random.choice(['CASH', 'TRANSFER']),
            'cashier':          cashier,
            'branch':           branch_main,
            'completed_at':     tz.now() - timedelta(hours=random.randint(0, 48)),
        }
    )
print('  ✓ 10 transacciones creadas')

print()
print('=' * 50)
print('DATOS DE PRUEBA CREADOS EXITOSAMENTE')
print('=' * 50)
print()
print('Usuarios para login:')
print('  admin      / Admin123!   (Administrador)')
print('  supervisor / Super123!   (Supervisor)')
print('  cajero     / Cajero123!  (Cajero)')
print()
print('URL Login: http://localhost:3000/login')
print('URL Admin: http://localhost:8000/admin/')