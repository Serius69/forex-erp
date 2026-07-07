"""
Management command: seed_rate_sources

Carga o actualiza todas las fuentes de integración en ExchangeRateSource.
Idempotente: si id_fuente ya existe, actualiza sin duplicar.

Uso:
    python manage.py seed_rate_sources
    python manage.py seed_rate_sources --dry-run
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

SOURCES_DATA = [
    # ── Binance P2P (por fiat) ──────────────────────────────────────────────
    {
        'id_fuente':      'binance_p2p_bob',
        'name':           'Binance P2P — BOB',
        'tipo_fuente':    'P2P',
        'source_type':    'digital',
        'url':            'https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search',
        'metodo_http':    'POST',
        'requiere_auth':  False,
        'pais_referencia': 'BO',
        'priority':       10,
        'weight':         '1.50',
        'fetch_interval_min': 5,
    },
    {
        'id_fuente':      'binance_p2p_ars',
        'name':           'Binance P2P — ARS',
        'tipo_fuente':    'P2P',
        'source_type':    'digital',
        'url':            'https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search',
        'metodo_http':    'POST',
        'requiere_auth':  False,
        'pais_referencia': 'AR',
        'priority':       9,
        'weight':         '1.20',
        'fetch_interval_min': 5,
    },
    {
        'id_fuente':      'binance_p2p_clp',
        'name':           'Binance P2P — CLP',
        'tipo_fuente':    'P2P',
        'source_type':    'digital',
        'url':            'https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search',
        'metodo_http':    'POST',
        'requiere_auth':  False,
        'pais_referencia': 'CL',
        'priority':       8,
        'weight':         '1.10',
        'fetch_interval_min': 5,
    },
    {
        'id_fuente':      'binance_p2p_pen',
        'name':           'Binance P2P — PEN',
        'tipo_fuente':    'P2P',
        'source_type':    'digital',
        'url':            'https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search',
        'metodo_http':    'POST',
        'requiere_auth':  False,
        'pais_referencia': 'PE',
        'priority':       8,
        'weight':         '1.10',
        'fetch_interval_min': 5,
    },
    {
        'id_fuente':      'binance_p2p_brl',
        'name':           'Binance P2P — BRL',
        'tipo_fuente':    'P2P',
        'source_type':    'digital',
        'url':            'https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search',
        'metodo_http':    'POST',
        'requiere_auth':  False,
        'pais_referencia': 'BR',
        'priority':       8,
        'weight':         '1.10',
        'fetch_interval_min': 5,
    },
    {
        'id_fuente':      'binance_p2p_eur',
        'name':           'Binance P2P — EUR',
        'tipo_fuente':    'P2P',
        'source_type':    'digital',
        'url':            'https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search',
        'metodo_http':    'POST',
        'requiere_auth':  False,
        'pais_referencia': 'EU',
        'priority':       8,
        'weight':         '1.10',
        'fetch_interval_min': 5,
    },
    # ── Otros P2P ──────────────────────────────────────────────────────────────
    {
        'id_fuente':      'bitget_p2p',
        'name':           'Bitget P2P — BOB',
        'tipo_fuente':    'P2P',
        'source_type':    'digital',
        'url':            'https://api.bitget.com/api/v2/p2p/merchant-ad-list',
        'metodo_http':    'GET',
        'requiere_auth':  False,
        'pais_referencia': 'BO',
        'priority':       7,
        'weight':         '1.00',
        'fetch_interval_min': 5,
    },
    {
        'id_fuente':      'bybit_p2p',
        'name':           'Bybit P2P — BOB',
        'tipo_fuente':    'P2P',
        'source_type':    'digital',
        'url':            'https://api.bybit.com/v5/p2p/item/online',
        'metodo_http':    'GET',
        'requiere_auth':  False,
        'pais_referencia': 'BO',
        'priority':       7,
        'weight':         '1.00',
        'fetch_interval_min': 5,
    },
    # ── Wallets / Remesas ──────────────────────────────────────────────────────
    {
        'id_fuente':      'airtm',
        'name':           'Airtm',
        'tipo_fuente':    'WALLET',
        'source_type':    'digital',
        'url':            'https://www.airtm.com',
        'metodo_http':    'GET',
        'requiere_auth':  False,
        'pais_referencia': 'BO',
        'priority':       6,
        'weight':         '0.90',
        'fetch_interval_min': 15,
    },
    {
        'id_fuente':      'eldorado',
        'name':           'El Dorado',
        'tipo_fuente':    'EXCHANGE',
        'source_type':    'digital',
        'url':            'https://api.eldorado.io/api/v1/rates',
        'metodo_http':    'GET',
        'requiere_auth':  True,
        'pais_referencia': 'BO',
        'priority':       7,
        'weight':         '1.10',
        'fetch_interval_min': 5,
    },
    {
        'id_fuente':      'okx_convert',
        'name':           'OKX Convert',
        'tipo_fuente':    'EXCHANGE',
        'source_type':    'digital',
        'url':            'https://www.okx.com/api/v5/asset/convert/estimate-quote',
        'metodo_http':    'GET',
        'requiere_auth':  False,
        'pais_referencia': 'BO',
        'priority':       5,
        'weight':         '0.80',
        'fetch_interval_min': 10,
    },
    # ── Agregadores HTML ───────────────────────────────────────────────────────
    {
        'id_fuente':      'usdtbol',
        'name':           'USDTBol.com',
        'tipo_fuente':    'AGREGADOR',
        'source_type':    'parallel',
        'url':            'https://usdtbol.com',
        'metodo_http':    'GET',
        'requiere_auth':  False,
        'pais_referencia': 'BO',
        'priority':       4,
        'weight':         '0.75',
        'fetch_interval_min': 15,
    },
    {
        'id_fuente':      'ayudabolivia',
        'name':           'AyudaBolivia.com',
        'tipo_fuente':    'AGREGADOR',
        'source_type':    'parallel',
        'url':            'https://ayudabolivia.com',
        'metodo_http':    'GET',
        'requiere_auth':  False,
        'pais_referencia': 'BO',
        'priority':       4,
        'weight':         '0.70',
        'fetch_interval_min': 15,
    },
    {
        'id_fuente':      'dolarparalelobolivia',
        'name':           'DolarParaleloBolivia.net',
        'tipo_fuente':    'AGREGADOR',
        'source_type':    'parallel',
        'url':            'https://dolarparalelobolivia.net',
        'metodo_http':    'GET',
        'requiere_auth':  False,
        'pais_referencia': 'BO',
        'priority':       3,
        'weight':         '0.65',
        'fetch_interval_min': 15,
    },
    {
        'id_fuente':      'dolarbolivia',
        'name':           'DolarBolivia.net',
        'tipo_fuente':    'AGREGADOR',
        'source_type':    'parallel',
        'url':            'https://dolarbolivia.net',
        'metodo_http':    'GET',
        'requiere_auth':  False,
        'pais_referencia': 'BO',
        'priority':       3,
        'weight':         '0.65',
        'fetch_interval_min': 15,
    },
    {
        'id_fuente':      'dolarboliviahoy',
        'name':           'DolarBoliviaHoy',
        'tipo_fuente':    'AGREGADOR',
        'source_type':    'parallel',
        'url':            'https://dolarboliviahoy.com',
        'metodo_http':    'GET',
        'requiere_auth':  False,
        'pais_referencia': 'BO',
        'priority':       3,
        'weight':         '0.60',
        'fetch_interval_min': 15,
    },
    {
        'id_fuente':      'bolivianblue',
        'name':           'BolivianBlue.net',
        'tipo_fuente':    'AGREGADOR',
        'source_type':    'parallel',
        'url':            'https://bolivianblue.net',
        'metodo_http':    'GET',
        'requiere_auth':  False,
        'pais_referencia': 'BO',
        'priority':       4,
        'weight':         '0.70',
        'fetch_interval_min': 15,
    },
    {
        'id_fuente':      'boliviadolarblue',
        'name':           'BoliviadolarBlue.com',
        'tipo_fuente':    'AGREGADOR',
        'source_type':    'parallel',
        'url':            'https://boliviadolarblue.com',
        'metodo_http':    'GET',
        'requiere_auth':  False,
        'pais_referencia': 'BO',
        'priority':       3,
        'weight':         '0.65',
        'fetch_interval_min': 15,
    },
    {
        'id_fuente':      'dolarbluebolivia_click',
        'name':           'DolarBlueBolivia.click',
        'tipo_fuente':    'AGREGADOR',
        'source_type':    'parallel',
        'url':            'https://dolarbluebolivia.click',
        'metodo_http':    'GET',
        'requiere_auth':  False,
        'pais_referencia': 'BO',
        'priority':       5,
        'weight':         '0.85',
        'fetch_interval_min': 15,
    },
    {
        'id_fuente':      'bolidolar',
        'name':           'BoliDolar.com',
        'tipo_fuente':    'AGREGADOR',
        'source_type':    'parallel',
        'url':            'https://bolidolar.com',
        'metodo_http':    'GET',
        'requiere_auth':  False,
        'pais_referencia': 'BO',
        'priority':       3,
        'weight':         '0.60',
        'fetch_interval_min': 15,
    },
    # ── SaldoAR ────────────────────────────────────────────────────────────────
    {
        'id_fuente':      'saldoar',
        'name':           'SaldoAR (ARS/USD)',
        'tipo_fuente':    'AGREGADOR',
        'source_type':    'digital',
        'url':            'https://api.saldo.com.ar/json/rates/banco/banco_ar_usd',
        'metodo_http':    'GET',
        'requiere_auth':  False,
        'pais_referencia': 'AR',
        'priority':       5,
        'weight':         '0.82',
        'fetch_interval_min': 10,
    },
]


class Command(BaseCommand):
    help = 'Carga o actualiza todas las fuentes de integración en ExchangeRateSource'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Mostrar qué se haría sin modificar la DB',
        )

    def handle(self, *args, **options):
        from rates.models import ExchangeRateSource
        from decimal import Decimal

        dry_run  = options['dry_run']
        created  = 0
        updated  = 0
        skipped  = 0

        for data in SOURCES_DATA:
            id_fuente = data['id_fuente']
            name      = data['name']

            # Campos para update_or_create
            defaults = {
                'name':           name,
                'tipo_fuente':    data['tipo_fuente'],
                'source_type':    data['source_type'],
                'url':            data['url'],
                'metodo_http':    data['metodo_http'],
                'requiere_auth':  data['requiere_auth'],
                'pais_referencia': data['pais_referencia'],
                'priority':       data['priority'],
                'weight':         Decimal(data['weight']),
                'fetch_interval_min': data['fetch_interval_min'],
                'is_active':      True,
            }

            if dry_run:
                exists = ExchangeRateSource.objects.filter(id_fuente=id_fuente).exists()
                self.stdout.write(
                    f'  {"UPDATE" if exists else "CREATE"} {id_fuente} — {name}'
                )
                skipped += 1
                continue

            try:
                obj, was_created = ExchangeRateSource.objects.update_or_create(
                    id_fuente=id_fuente,
                    defaults=defaults,
                )
                if was_created:
                    created += 1
                    self.stdout.write(self.style.SUCCESS(f'  CREATED {id_fuente} — {name}'))
                else:
                    updated += 1
                    self.stdout.write(f'  updated {id_fuente} — {name}')
            except Exception as exc:
                # Puede fallar si 'name' ya existe con otro id_fuente
                # En ese caso actualizamos solo los campos de integración
                try:
                    obj = ExchangeRateSource.objects.get(name=name)
                    obj.id_fuente = id_fuente
                    for k, v in defaults.items():
                        setattr(obj, k, v)
                    obj.save()
                    updated += 1
                    self.stdout.write(f'  patched {id_fuente} — {name}')
                except Exception as exc2:
                    self.stderr.write(
                        self.style.ERROR(f'  ERROR {id_fuente}: {exc} / {exc2}')
                    )

        total = len(SOURCES_DATA)
        if dry_run:
            self.stdout.write(self.style.WARNING(
                f'\nDRY RUN — {total} fuentes procesadas (sin cambios en DB)'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'\nSeed completado: {created} creadas, {updated} actualizadas '
                f'de {total} fuentes totales.'
            ))
