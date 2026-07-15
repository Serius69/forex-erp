"""
Deriva la serie de tasas de la EMPRESA (market_type='paralelo_fisico_empresa')
a partir de las TRANSACCIONES reales.

Para cada (divisa vs BOB, día) calcula la tasa efectiva realizada:
  · buy_rate  = mediana de exchange_rate de las transacciones BUY  de ese día
  · sell_rate = mediana de exchange_rate de las transacciones SELL de ese día

Robustez frente a errores de captura manual:
  1. Mediana diaria (absorbe outliers dentro del día).
  2. Filtro por mediana móvil (descarta días aislados absurdos, preservando la
     tendencia real — en Bolivia el paralelo pasó de ~7 a ~15 en 2024-2025).
  3. Si un día tiene un solo lado, se sintetiza el faltante con el spread típico
     de la divisa (marcado con menor 'confidence').

Idempotente. Uso:
    python manage.py derive_empresa_rates
    python manage.py derive_empresa_rates --min-per-day 1 --window 15
"""
from datetime import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction
from django.utils import timezone

from rates.models import Currency, ExchangeRate
from transactions.models import Transaction

EMPRESA = 'paralelo_fisico_empresa'


class Command(BaseCommand):
    help = 'Deriva paralelo_fisico_empresa (tasa efectiva diaria) desde las transacciones'

    def add_arguments(self, parser):
        parser.add_argument('--window', type=int, default=15,
                            help='Ventana (días) de la mediana móvil para filtrar outliers.')
        parser.add_argument('--max-dev', type=float, default=0.45,
                            help='Desviación relativa máx. vs mediana móvil (0.45 = ±45%%).')
        parser.add_argument('--purge', action='store_true',
                            help='Borra las tasas empresa derivadas antes de recalcular.')

    def handle(self, *args, **opts):
        import pandas as pd

        bob = Currency.objects.filter(code='BOB').first()
        if not bob:
            self.stderr.write(self.style.ERROR('Falta BOB — corre seed_currencies'))
            return

        currencies = {c.code: c for c in Currency.objects.all()}

        if opts['purge']:
            n = ExchangeRate.objects.filter(
                market_type=EMPRESA, source='transacciones_reales').delete()[0]
            self.stdout.write(f'Purgadas {n} tasas empresa derivadas previas')

        # ── Cargar transacciones con tasa hacia BOB ────────────────────────────
        qs = (Transaction.objects
              .filter(currency_to__code='BOB')
              .exclude(exchange_rate__isnull=True)
              .values('currency_from__code', 'transaction_type',
                      'exchange_rate', 'created_at'))
        df = pd.DataFrame(list(qs))
        if df.empty:
            self.stderr.write(self.style.ERROR('No hay transacciones hacia BOB'))
            return

        df['rate'] = pd.to_numeric(df['exchange_rate'], errors='coerce')
        df['day'] = pd.to_datetime(df['created_at']).dt.tz_convert('America/La_Paz').dt.date
        df = df.dropna(subset=['rate'])
        df = df[df['rate'] > 0]

        total_written = 0
        summary = {}
        for code, cur in currencies.items():
            sub = df[df['currency_from__code'] == code]
            if sub.empty:
                continue
            series = self._build_pair_series(pd, sub, opts['window'], opts['max_dev'])
            if not series:
                continue
            written = self._write(cur, bob, series)
            total_written += written
            summary[f'{code}/BOB'] = written

        self.stdout.write(self.style.SUCCESS(
            f'Tasas empresa derivadas: {total_written} filas'))

        # Serie por fecha → deja vigente solo la más reciente por (divisa, mercado).
        from rates.rate_expiry import expire_stale_active_rates
        closed = expire_stale_active_rates(market_type=EMPRESA)
        if closed:
            self.stdout.write(self.style.SUCCESS(
                f'Normalizadas {closed} tasas históricas (una vigente por divisa)'))

        for k, v in sorted(summary.items(), key=lambda x: -x[1]):
            self.stdout.write(f'  {k:22} {v}')
        grand = ExchangeRate.objects.filter(market_type=EMPRESA).count()
        self.stdout.write(self.style.SUCCESS(f'TOTAL paralelo_fisico_empresa en BD: {grand}'))

    # ──────────────────────────────────────────────────────────────────────────
    def _build_pair_series(self, pd, sub, window, max_dev):
        """Devuelve [(date, buy, sell, confidence), ...] para una divisa."""
        def daily_median(side):
            s = sub[sub['transaction_type'] == side]
            if s.empty:
                return pd.Series(dtype='float64')
            g = s.groupby('day')['rate'].median()
            g.index = pd.to_datetime(g.index)
            return g.sort_index()

        buy = self._despike(pd, daily_median('BUY'), window, max_dev)
        sell = self._despike(pd, daily_median('SELL'), window, max_dev)

        # spread típico (sell/buy) de días con ambos lados
        common = buy.index.intersection(sell.index)
        if len(common) >= 3:
            ratio = (sell.loc[common] / buy.loc[common])
            typ_ratio = float(ratio[(ratio > 1) & (ratio < 1.5)].median() or 1.03)
        else:
            typ_ratio = 1.03
        if not (1.0 < typ_ratio < 1.5):
            typ_ratio = 1.03

        all_days = buy.index.union(sell.index)
        out = []
        for d in all_days:
            b = buy.get(d)
            s = sell.get(d)
            conf = Decimal('0.90')
            if b is not None and s is not None:
                bb, ss = float(b), float(s)
                if bb > ss:
                    bb, ss = ss, bb
            elif b is not None:
                bb = float(b); ss = bb * typ_ratio; conf = Decimal('0.65')
            else:
                ss = float(s); bb = ss / typ_ratio; conf = Decimal('0.65')
            if bb <= 0 or ss <= 0:
                continue
            out.append((d.date(), round(bb, 4), round(ss, 4), conf))
        return out

    @staticmethod
    def _despike(pd, s, window, max_dev):
        """Descarta puntos que se desvían > max_dev de la mediana móvil."""
        if len(s) < 5:
            return s
        roll = s.rolling(window, center=True, min_periods=3).median()
        roll = roll.bfill().ffill()
        keep = (s - roll).abs() <= (roll * max_dev)
        return s[keep]

    # ──────────────────────────────────────────────────────────────────────────
    @db_transaction.atomic
    def _write(self, cur, bob, series):
        q4 = Decimal('0.0001')
        written = 0
        for d, buy, sell, conf in series:
            valid_from = timezone.make_aware(datetime(d.year, d.month, d.day))
            buy_d = Decimal(str(buy)).quantize(q4)
            sell_d = Decimal(str(sell)).quantize(q4)
            mid = ((buy_d + sell_d) / 2).quantize(q4)
            ExchangeRate.objects.update_or_create(
                currency_from=cur,
                currency_to=bob,
                valid_from=valid_from,
                market_type=EMPRESA,
                rate_source=None,
                defaults={
                    'official_rate': mid,
                    'buy_rate': buy_d,
                    'sell_rate': sell_d,
                    'avg_rate': mid,
                    'source': 'transacciones_reales',
                    'source_method': 'MANUAL',
                    'confidence': conf,
                },
            )
            written += 1
        return written
