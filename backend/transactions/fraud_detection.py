# transactions/fraud_detection.py
"""
Motor anti-fraude para transacciones de cambio.

Decisiones posibles:
  APPROVE         — sin flags de riesgo, proceder normalmente
  REQUIRE_APPROVAL — riesgo medio, requiere aprobación de supervisor
  BLOCK           — riesgo alto, bloquear la operación

Reglas configurables desde Django Admin (modelo FraudRule).
Los umbrales se cargan desde la DB; si la DB no está disponible
se usa un conjunto de defaults seguros en memoria.
"""
import logging
import statistics
from dataclasses import dataclass, field
from decimal import Decimal
from typing import NamedTuple

from django.core.cache import cache
from django.db import models
from django.utils import timezone

log = logging.getLogger('transactions.fraud')

# ── Resultado de evaluación ────────────────────────────────────────────────────

APPROVE          = 'APPROVE'
REQUIRE_APPROVAL = 'REQUIRE_APPROVAL'
BLOCK            = 'BLOCK'


@dataclass
class FraudResult:
    decision:    str              # APPROVE | REQUIRE_APPROVAL | BLOCK
    score:       Decimal          # 0.0000–1.0000
    flags:       list[str]        = field(default_factory=list)
    details:     dict             = field(default_factory=dict)


# ── Modelo de regla configurable ──────────────────────────────────────────────

class FraudRule(models.Model):
    """
    Regla anti-fraude configurable desde Django Admin sin tocar código.
    """
    RULE_TYPES = [
        ('VELOCITY',        'Velocidad de transacciones (por hora)'),
        ('AMOUNT_ANOMALY',  'Anomalía de monto (σ desviaciones)'),
        ('RATE_SANITY',     'Sanidad de tasa vs paralela (%)'),
        ('DUPLICATE',       'Detección de duplicados (minutos)'),
        ('BLACKLIST',       'Lista negra / PEP'),
        ('HIGH_VALUE',      'Monto alto en BOB'),
    ]
    DECISIONS = [
        ('APPROVE',          'Aprobar'),
        ('REQUIRE_APPROVAL', 'Requiere aprobación'),
        ('BLOCK',            'Bloquear'),
    ]

    name        = models.CharField(max_length=100, unique=True)
    rule_type   = models.CharField(max_length=20, choices=RULE_TYPES, db_index=True)
    threshold   = models.DecimalField(
        max_digits=12, decimal_places=4,
        help_text=(
            'VELOCITY: max transacciones/hora; '
            'AMOUNT_ANOMALY: número de σ; '
            'RATE_SANITY: % desviación máxima; '
            'DUPLICATE: ventana en minutos; '
            'HIGH_VALUE: monto mínimo en BOB para disparar.'
        ),
    )
    decision    = models.CharField(max_length=20, choices=DECISIONS, default='REQUIRE_APPROVAL')
    score_delta = models.DecimalField(
        max_digits=5, decimal_places=4, default=Decimal('0.3000'),
        help_text='Cuánto suma esta regla al fraud_score (0–1).',
    )
    is_active   = models.BooleanField(default=True, db_index=True)
    description = models.TextField(blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        app_label           = 'transactions'
        db_table            = 'transaction_fraud_rule'
        ordering            = ['rule_type', 'name']
        verbose_name        = 'Regla Anti-Fraude'
        verbose_name_plural = 'Reglas Anti-Fraude'

    def __str__(self):
        return f'{self.name} ({self.rule_type}) → {self.decision}'


# ── Engine ─────────────────────────────────────────────────────────────────────

class FraudDetectionEngine:
    """
    Evalúa una transacción potencial contra todas las reglas activas.

    Uso típico (en TransactionCreateSerializer.validate o en la vista):

        engine = FraudDetectionEngine()
        result = engine.evaluate(
            transaction_type='BUY',
            currency_from='USD',
            currency_to='BOB',
            amount_from=10_000,
            amount_to=68_900,
            exchange_rate=Decimal('6.89'),
            customer=customer_instance,   # puede ser None
            cashier=request.user,
            branch=branch,
        )
        if result.decision == BLOCK:
            raise ValidationError({'non_field_errors': ['Transacción bloqueada por control antifraude.']})
    """

    _CACHE_KEY    = 'fraud_rules_active'
    _CACHE_TTL    = 120  # segundos — recarga reglas cada 2 minutos

    # Defaults seguros cuando la DB no está disponible
    _SAFE_DEFAULTS = [
        {'rule_type': 'VELOCITY',       'threshold': Decimal('10'),    'decision': REQUIRE_APPROVAL, 'score_delta': Decimal('0.30')},
        {'rule_type': 'AMOUNT_ANOMALY', 'threshold': Decimal('3'),     'decision': REQUIRE_APPROVAL, 'score_delta': Decimal('0.25')},
        {'rule_type': 'RATE_SANITY',    'threshold': Decimal('5'),     'decision': REQUIRE_APPROVAL, 'score_delta': Decimal('0.35')},
        {'rule_type': 'DUPLICATE',      'threshold': Decimal('5'),     'decision': BLOCK,            'score_delta': Decimal('0.60')},
        {'rule_type': 'HIGH_VALUE',     'threshold': Decimal('100000'),'decision': REQUIRE_APPROVAL, 'score_delta': Decimal('0.20')},
    ]

    # ── Carga de reglas ───────────────────────────────────────────────────────

    def _load_rules(self) -> list[dict]:
        cached = cache.get(self._CACHE_KEY)
        if cached is not None:
            return cached
        try:
            rules = list(
                FraudRule.objects.filter(is_active=True)
                .values('rule_type', 'threshold', 'decision', 'score_delta', 'name')
            )
            cache.set(self._CACHE_KEY, rules, self._CACHE_TTL)
            return rules
        except Exception as exc:
            log.warning('FRAUD_RULES_DB_FAIL err=%s — using safe defaults', exc)
            return self._SAFE_DEFAULTS

    def _rules_by_type(self, rules: list[dict]) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        for r in rules:
            out.setdefault(r['rule_type'], []).append(r)
        return out

    # ── Evaluación principal ──────────────────────────────────────────────────

    def evaluate(
        self,
        *,
        transaction_type: str,
        currency_from: str,
        currency_to: str,
        amount_from: int,
        amount_to: int,
        exchange_rate: Decimal,
        customer=None,
        cashier=None,
        branch=None,
        parallel_rate: Decimal | None = None,
    ) -> FraudResult:
        """
        Retorna FraudResult con decision, score y flags disparados.
        No lanza excepciones — errores internos resultanr en APPROVE (fail-open).
        """
        try:
            return self._evaluate_inner(
                transaction_type=transaction_type,
                currency_from=currency_from,
                currency_to=currency_to,
                amount_from=amount_from,
                amount_to=amount_to,
                exchange_rate=exchange_rate,
                customer=customer,
                cashier=cashier,
                branch=branch,
                parallel_rate=parallel_rate,
            )
        except Exception as exc:
            log.error('FRAUD_ENGINE_FAIL err=%s', exc, exc_info=True)
            return FraudResult(decision=APPROVE, score=Decimal('0'))

    def _evaluate_inner(self, **kwargs) -> FraudResult:
        rules      = self._load_rules()
        by_type    = self._rules_by_type(rules)
        score      = Decimal('0')
        flags: list[str] = []
        decisions: list[str] = []
        details    = {}

        # ── Velocidad ─────────────────────────────────────────────────────────
        if 'VELOCITY' in by_type and kwargs.get('cashier'):
            for rule in by_type['VELOCITY']:
                velocity, v_detail = self._check_velocity(
                    cashier=kwargs['cashier'],
                    threshold=int(rule['threshold']),
                )
                if velocity:
                    flags.append(f"VELOCITY:{rule.get('name','velocity')}")
                    decisions.append(rule['decision'])
                    score += rule['score_delta']
                    details['velocity'] = v_detail

        # ── Anomalía de monto ─────────────────────────────────────────────────
        if 'AMOUNT_ANOMALY' in by_type and kwargs.get('customer'):
            for rule in by_type['AMOUNT_ANOMALY']:
                anomaly, a_detail = self._check_amount_anomaly(
                    customer=kwargs['customer'],
                    amount=kwargs['amount_from'],
                    sigma_threshold=float(rule['threshold']),
                    currency_from=kwargs.get('currency_from'),
                )
                if anomaly:
                    flags.append(f"AMOUNT_ANOMALY:{rule.get('name','anomaly')}")
                    decisions.append(rule['decision'])
                    score += rule['score_delta']
                    details['amount_anomaly'] = a_detail

        # ── Sanidad de tasa vs paralela ───────────────────────────────────────
        if 'RATE_SANITY' in by_type and kwargs.get('parallel_rate'):
            for rule in by_type['RATE_SANITY']:
                sanity, s_detail = self._check_rate_sanity(
                    exchange_rate=kwargs['exchange_rate'],
                    parallel_rate=kwargs['parallel_rate'],
                    max_deviation_pct=float(rule['threshold']),
                )
                if sanity:
                    flags.append(f"RATE_SANITY:{rule.get('name','rate_sanity')}")
                    decisions.append(rule['decision'])
                    score += rule['score_delta']
                    details['rate_sanity'] = s_detail

        # ── Detección de duplicados ───────────────────────────────────────────
        if 'DUPLICATE' in by_type:
            for rule in by_type['DUPLICATE']:
                dup, d_detail = self._check_duplicate(
                    customer=kwargs.get('customer'),
                    cashier=kwargs.get('cashier'),
                    currency_from=kwargs['currency_from'],
                    amount_from=kwargs['amount_from'],
                    window_minutes=int(rule['threshold']),
                )
                if dup:
                    flags.append(f"DUPLICATE:{rule.get('name','duplicate')}")
                    decisions.append(rule['decision'])
                    score += rule['score_delta']
                    details['duplicate'] = d_detail

        # ── Blacklist / PEP ───────────────────────────────────────────────────
        if 'BLACKLIST' in by_type and kwargs.get('customer'):
            bl, bl_detail = self._check_blacklist(kwargs['customer'])
            if bl:
                for rule in by_type['BLACKLIST']:
                    flags.append(f"BLACKLIST:{rule.get('name','blacklist')}")
                    decisions.append(rule['decision'])
                    score += rule['score_delta']
                details['blacklist'] = bl_detail

        # ── Monto alto en BOB ─────────────────────────────────────────────────
        if 'HIGH_VALUE' in by_type:
            # Normalizar todo a BOB
            amount_bob = kwargs['amount_to'] if kwargs['currency_to'] == 'BOB' else kwargs['amount_from']
            for rule in by_type['HIGH_VALUE']:
                if Decimal(amount_bob) >= rule['threshold']:
                    flags.append(f"HIGH_VALUE:{rule.get('name','high_value')}")
                    decisions.append(rule['decision'])
                    score += rule['score_delta']
                    details['high_value'] = {'amount_bob': amount_bob, 'threshold': str(rule['threshold'])}

        # ── Score final ───────────────────────────────────────────────────────
        score = min(score, Decimal('1.0000'))

        # La decisión más restrictiva prevalece
        if BLOCK in decisions:
            decision = BLOCK
        elif REQUIRE_APPROVAL in decisions:
            decision = REQUIRE_APPROVAL
        else:
            decision = APPROVE

        return FraudResult(decision=decision, score=score, flags=flags, details=details)

    # ── Reglas individuales ───────────────────────────────────────────────────

    def _check_velocity(self, cashier, threshold: int) -> tuple[bool, dict]:
        """
        Comprueba que el cajero no supere `threshold` transacciones en la última hora.
        """
        try:
            from .models import Transaction
            one_hour_ago = timezone.now() - timezone.timedelta(hours=1)
            count = Transaction.objects.filter(
                cashier=cashier,
                created_at__gte=one_hour_ago,
                status__in=('COMPLETED', 'PROCESSING', 'APPROVED', 'PENDING'),
            ).count()
            detail = {'count_last_hour': count, 'threshold': threshold}
            return count >= threshold, detail
        except Exception as exc:
            log.debug('FRAUD_VELOCITY_ERR %s', exc)
            return False, {}

    def _check_amount_anomaly(self, customer, amount: int, sigma_threshold: float,
                              currency_from: str = None) -> tuple[bool, dict]:
        """
        Compara `amount` con la media histórica del cliente ± sigma_threshold σ.
        Requiere al menos 10 transacciones previas para calcular estadísticas fiables.

        Se acota a la MISMA divisa: mezclar montos de distintas divisas (p.ej. 100
        USD y 700 BOB) hace la media/desviación —y el z-score— sin sentido.
        """
        try:
            from .models import Transaction
            qs = Transaction.objects.filter(customer=customer, status='COMPLETED')
            if currency_from:
                qs = qs.filter(currency_from__code=currency_from)
            amounts = list(qs.values_list('amount_from', flat=True)[:200])
            if len(amounts) < 10:
                return False, {'reason': 'insufficient_history'}

            mean = statistics.mean(amounts)
            stdev = statistics.stdev(amounts)
            if stdev == 0:
                return False, {'reason': 'zero_stdev'}

            z_score = abs(amount - mean) / stdev
            detail = {'z_score': round(z_score, 4), 'mean': round(mean, 2), 'stdev': round(stdev, 2)}
            return z_score > sigma_threshold, detail
        except Exception as exc:
            log.debug('FRAUD_ANOMALY_ERR %s', exc)
            return False, {}

    def _check_rate_sanity(
        self, exchange_rate: Decimal, parallel_rate: Decimal, max_deviation_pct: float
    ) -> tuple[bool, dict]:
        """
        Verifica que la tasa operada no se desvíe más de `max_deviation_pct`%
        de la tasa paralela de referencia.
        """
        try:
            if not parallel_rate or parallel_rate == 0:
                return False, {'reason': 'no_parallel_rate'}
            deviation_pct = abs(float(exchange_rate - parallel_rate) / float(parallel_rate)) * 100
            detail = {
                'exchange_rate':    str(exchange_rate),
                'parallel_rate':    str(parallel_rate),
                'deviation_pct':    round(deviation_pct, 4),
                'max_allowed_pct':  max_deviation_pct,
            }
            return deviation_pct > max_deviation_pct, detail
        except Exception as exc:
            log.debug('FRAUD_RATE_ERR %s', exc)
            return False, {}

    def _check_duplicate(
        self, customer, cashier, currency_from: str, amount_from: int, window_minutes: int
    ) -> tuple[bool, dict]:
        """
        Detecta transacciones idénticas en los últimos `window_minutes` minutos
        (mismo cliente o cajero, misma divisa, mismo monto).
        """
        try:
            from .models import Transaction
            since = timezone.now() - timezone.timedelta(minutes=window_minutes)
            # Sin cliente real no se puede detectar un duplicado del MISMO cliente:
            # agrupar por cajero bloquearía operaciones idénticas de clientes
            # distintos (falsos positivos → 403). Se salta la regla.
            if not customer:
                return False, {'reason': 'no_customer'}

            qs = Transaction.objects.filter(
                customer=customer,
                currency_from__code=currency_from,
                amount_from=amount_from,
                created_at__gte=since,
                status__in=('COMPLETED', 'PROCESSING', 'APPROVED', 'PENDING'),
            )

            count = qs.count()
            detail = {'duplicate_count': count, 'window_minutes': window_minutes}
            return count > 0, detail
        except Exception as exc:
            log.debug('FRAUD_DUPLICATE_ERR %s', exc)
            return False, {}

    def _check_blacklist(self, customer) -> tuple[bool, dict]:
        """
        Verifica si el cliente está en lista negra (PEP) o tiene historial de fraude.
        Extensible: puede consultar listas externas UIAF/SEPRELAD.
        """
        try:
            is_pep = getattr(customer, 'is_pep', False)
            detail = {'is_pep': is_pep}
            # Aquí se pueden agregar comprobaciones adicionales:
            # - Consulta a listas OFAC / UIAF
            # - Historial de transacciones REVERSED por fraude
            return is_pep, detail
        except Exception as exc:
            log.debug('FRAUD_BLACKLIST_ERR %s', exc)
            return False, {}
