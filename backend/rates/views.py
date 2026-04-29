# rates/views.py
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.views import APIView
from django.utils import timezone
from django.core.cache import cache
from decimal import Decimal
from datetime import timedelta
from django.db.models import Avg, Min, Max
from django.db.models.functions import TruncDate, TruncHour
from .models import Currency, ExchangeRate, ExchangeRateSource, RateConfiguration
from .serializers import (
    CurrencySerializer, ExchangeRateSerializer,
    ExchangeRateSourceSerializer, RateConfigurationSerializer,
)
from .services import RateService

class CurrencyViewSet(viewsets.ModelViewSet):
    serializer_class   = CurrencySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Currency.objects.all()
        active_only = self.request.query_params.get('active_only', 'true').lower()
        if active_only == 'true':
            qs = qs.filter(is_active=True)
        return qs.order_by('code')

    def perform_destroy(self, instance):
        # Soft delete — never hard-delete currencies
        instance.is_active = False
        instance.save(update_fields=['is_active'])

    def _validate_base_currency(self, is_base, current_pk=None):
        if is_base:
            qs = Currency.objects.filter(is_base_currency=True)
            if current_pk:
                qs = qs.exclude(pk=current_pk)
            if qs.exists():
                from rest_framework.exceptions import ValidationError
                raise ValidationError({'is_base_currency': 'Ya existe una divisa base. Desactívela primero.'})

    def perform_create(self, serializer):
        self._validate_base_currency(serializer.validated_data.get('is_base_currency', False))
        serializer.save()

    def perform_update(self, serializer):
        self._validate_base_currency(
            serializer.validated_data.get('is_base_currency', serializer.instance.is_base_currency),
            current_pk=serializer.instance.pk,
        )
        serializer.save()

class ExchangeRateViewSet(viewsets.ModelViewSet):
    queryset = ExchangeRate.objects.all()
    serializer_class = ExchangeRateSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filtros opcionales
        currency_from = self.request.query_params.get('currency_from')
        currency_to = self.request.query_params.get('currency_to')
        active_only = self.request.query_params.get('active_only', 'true')
        
        if currency_from:
            queryset = queryset.filter(currency_from__code=currency_from)
        if currency_to:
            queryset = queryset.filter(currency_to__code=currency_to)
        if active_only.lower() == 'true':
            queryset = queryset.filter(valid_until__isnull=True)
        
        return queryset.select_related('currency_from', 'currency_to')
    
    @action(detail=False, methods=['GET'], permission_classes=[AllowAny], url_path='current')
    def current(self, request):
        """
        Tasas actuales con metadatos completos de trazabilidad y tasa primaria.
        ?include_sources=true  → incluye comparación multi-fuente por divisa
        """
        from .exchange_rate_service import ExchangeRateService

        include_sources  = request.query_params.get('include_sources', '').lower() == 'true'
        currency_filter  = request.query_params.get('currency')
        force_refresh    = request.query_params.get('refresh', '').lower() == 'true'

        qs = ExchangeRate.objects.filter(
            valid_until__isnull=True
        ).select_related('currency_from', 'currency_to', 'rate_source').order_by(
            'currency_from__code', '-is_primary', '-confidence'
        )

        if currency_filter:
            qs = qs.filter(currency_from__code=currency_filter.upper())

        serializer = ExchangeRateSerializer(qs, many=True)
        data = serializer.data

        if include_sources:
            service    = ExchangeRateService()
            currencies = set(rate['currency_from']['code'] for rate in data if isinstance(rate.get('currency_from'), dict))
            summaries  = {}
            for code in currencies:
                summary = service.get_rates_summary(code, force_refresh=force_refresh)
                if summary:
                    summaries[code] = summary.to_dict()
            return Response({'rates': data, 'summaries': summaries})

        return Response(data)

    @action(detail=False, methods=['GET'], permission_classes=[AllowAny], url_path='primary')
    def primary(self, request):
        """
        Devuelve ÚNICAMENTE las tasas primarias (is_primary=True) activas.
        Estas son las tasas que el sistema usa en transacciones.

        ?currency=USD  → filtra por divisa específica
        """
        from .exchange_rate_service import ExchangeRateService

        currency_filter = request.query_params.get('currency')
        service         = ExchangeRateService()

        currencies = Currency.objects.filter(is_active=True).exclude(code='BOB')
        if currency_filter:
            currencies = currencies.filter(code=currency_filter.upper())

        result = {}
        for cur in currencies:
            rate = service.get_primary_rate(cur.code)
            if not rate:
                continue
            result[cur.code] = {
                'currency_from':  cur.code,
                'currency_to':    'BOB',
                'scale_factor':   cur.scale_factor,
                'buy_rate':       str(rate.buy_rate),
                'sell_rate':      str(rate.sell_rate),
                'official_rate':  str(rate.official_rate),
                'avg_rate':       str(rate.avg_rate or (rate.buy_rate + rate.sell_rate) / Decimal('2')),
                'source_method':  rate.source_method,
                'source_url':     rate.source_url,
                'market_type':    rate.market_type,
                'confidence':     float(rate.confidence),
                'fetched_at':     rate.fetched_at.isoformat() if rate.fetched_at else None,
                'is_validated':   rate.is_validated,
                'is_primary':     rate.is_primary,
                'requires_warning': rate.requires_warning,
                'is_safe_for_transaction': (
                    rate.source_method != 'INFERENCE'
                    and float(rate.confidence) >= 0.70
                ),
                'updated_at':     rate.valid_from.isoformat() if rate.valid_from else None,
            }

        return Response(result)

    @action(detail=False, methods=['GET'], permission_classes=[IsAuthenticated], url_path='sources-summary')
    def sources_summary(self, request):
        """
        Resumen multi-fuente para una divisa: estadísticas, divergencias y comparación.
        ?currency=USD  (requerido)
        ?refresh=true  → forzar refresco de cache
        """
        from .exchange_rate_service import ExchangeRateService

        currency_code = request.query_params.get('currency', 'USD')
        force_refresh = request.query_params.get('refresh', '').lower() == 'true'

        service = ExchangeRateService()
        summary = service.get_rates_summary(currency_code, force_refresh=force_refresh)
        if not summary:
            return Response(
                {'error': f'No hay tasas activas para {currency_code}/BOB'},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(summary.to_dict())

    @action(detail=False, methods=['GET'], permission_classes=[IsAuthenticated], url_path='divergences')
    def divergences(self, request):
        """Detecta divergencias entre fuentes de tasas. Genera alerta si > X%."""
        from .exchange_rate_service import ExchangeRateService

        threshold = float(request.query_params.get('threshold', 5.0))
        service   = ExchangeRateService()
        result    = service.detect_divergences(threshold_pct=threshold)
        return Response({
            'threshold_pct':    threshold,
            'divergence_count': len(result),
            'divergences':      result,
            'checked_at':       timezone.now().isoformat(),
        })
    
    @action(detail=False, methods=['POST'])
    def update_rates(self, request):
        """Actualiza las tasas desde fuentes externas"""
        if request.user.role != 'ADMIN':
            return Response(
                {'error': 'Solo administradores pueden actualizar tasas'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        source = request.data.get('source', 'BCB')
        service = RateService()

        try:
            rates = service.fetch_official_rates(source)
            # Re-evaluate primary rates after manual update
            try:
                from .tasks import mark_primary_rates_task
                mark_primary_rates_task.delay()
            except Exception:
                pass
            return Response({
                'success': True,
                'rates': rates,
                'source': source,
                'timestamp': timezone.now()
            })
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['POST'], permission_classes=[AllowAny])
    def calculate(self, request):
        """Calcula el cambio de divisas"""
        amount = request.data.get('amount')
        currency_from = request.data.get('currency_from')
        currency_to = request.data.get('currency_to', 'BOB')
        transaction_type = request.data.get('transaction_type')
        
        if not all([amount, currency_from, transaction_type]):
            return Response(
                {'error': 'Faltan parámetros requeridos'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            from .exchange_rate_service import ExchangeRateService
            svc    = ExchangeRateService()
            result = svc.calculate_exchange(
                Decimal(str(amount)),
                currency_from,
                currency_to,
                transaction_type,
            )
            return Response(result)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=False, methods=['GET'], permission_classes=[AllowAny], url_path='live')
    def live(self, request):
        """
        GET /api/rates/exchange-rates/live/

        Obtiene la mejor tasa real disponible usando el RateEngine.
        Prioridad: Binance P2P → DolarBlueBolivia → DB cache → BCB ref

        ?currency=USD     — divisa específica (default: USD)
        ?all=true         — todas las divisas activas
        ?refresh=true     — ignorar caché

        Respuesta:
          {
            pair: "USD/BOB",
            buy: X, sell: Y, spread: Z, spread_pct: W,
            source: "binance",  (binance | dolarblue | db_cache | bcb_ref)
            source_url: "...",
            confidence: 0.95,
            timestamp: "...",
            is_live: true,
            anomalies: []
          }
        """
        from .engine import RateEngine

        fetch_all     = request.query_params.get('all', '').lower() == 'true'
        force_refresh = request.query_params.get('refresh', '').lower() == 'true'
        currency      = request.query_params.get('currency', 'USD').upper()

        engine = RateEngine()

        if fetch_all:
            cache_key = 'engine_live_all'
            if not force_refresh:
                cached = cache.get(cache_key)
                if cached:
                    return Response(cached)
            rates   = engine.get_all_rates()
            payload = {code: r.to_dict() for code, r in rates.items()}
            cache.set(cache_key, payload, 60)
            return Response(payload)

        cache_key = f'engine_live_{currency}'
        if not force_refresh:
            cached = cache.get(cache_key)
            if cached:
                return Response(cached)

        rate = engine.get_best_rate(currency)
        if not rate:
            return Response(
                {'error': f'No hay tasa disponible para {currency}/BOB'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        payload = rate.to_dict()
        cache.set(cache_key, payload, 60)  # Cache 1 minuto
        return Response(payload)


class LiveRatesView(viewsets.ViewSet):
    """
    GET /api/rates/live/
    Devuelve las mejores tasas disponibles por divisa desde la DB,
    priorizando: parallel > digital > bcb > official.

    Opcionalmente acepta ?market=parallel|digital|bcb|official para filtrar
    por tipo de mercado.

    Formato de respuesta:
      {
        "USD": {"buy": 9.30, "sell": 9.60, "official": 6.96,
                "market_type": "parallel", "scale_factor": 1,
                "sources": ["PARALELO_EST"], "updated_at": "..."},
        "CLP": {...},
        ...
      }
    """
    permission_classes = [AllowAny]

    def list(self, request):
        from .aggregator import RateAggregator, MARKET_PRIORITY
        from .models import Currency, ExchangeRate
        from django.utils import timezone

        market_filter = request.query_params.get('market')
        force_refresh = request.query_params.get('refresh', '').lower() == 'true'

        cache_key = f"live_rates_{market_filter or 'all'}"
        if not force_refresh:
            cached = cache.get(cache_key)
            if cached:
                return Response(cached)

        currencies = Currency.objects.filter(is_active=True).exclude(code='BOB')
        bob        = Currency.objects.filter(code='BOB').first()
        if not bob:
            return Response({'error': 'BOB currency not configured'}, status=500)

        agg    = RateAggregator()
        result = {}

        for currency in currencies:
            market_order = (
                [market_filter] if market_filter and market_filter in MARKET_PRIORITY
                else sorted(MARKET_PRIORITY, key=lambda m: MARKET_PRIORITY[m], reverse=True)
            )

            for market in market_order:
                rate = (
                    ExchangeRate.objects
                    .filter(
                        currency_from = currency,
                        currency_to   = bob,
                        market_type   = market,
                        valid_until__isnull = True,
                    )
                    .select_related('rate_source')
                    .order_by('-valid_from')
                    .first()
                )
                if rate:
                    result[currency.code] = {
                        'buy':          float(rate.buy_rate),
                        'sell':         float(rate.sell_rate),
                        'official':     float(rate.official_rate),
                        'market_type':  rate.market_type,
                        'scale_factor': currency.scale_factor,
                        'source':       rate.source or '',
                        'source_name':  rate.rate_source.name if rate.rate_source else rate.source,
                        'updated_at':   rate.valid_from.isoformat() if rate.valid_from else None,
                    }
                    break

        # Cache 5 min
        cache.set(cache_key, result, 300)
        return Response(result)

    def retrieve(self, request, pk=None):
        """GET /api/rates/live/{currency_code}/ — tasa individual."""
        from .aggregator import RateAggregator, MARKET_PRIORITY
        from .models import Currency, ExchangeRate

        if not pk:
            return Response({'error': 'currency_code required'}, status=400)

        code = pk.upper()
        try:
            currency = Currency.objects.get(code=code)
            bob      = Currency.objects.get(code='BOB')
        except Currency.DoesNotExist:
            return Response({'error': f'Currency {code} not found'}, status=404)

        for market in sorted(MARKET_PRIORITY, key=lambda m: MARKET_PRIORITY[m], reverse=True):
            rate = (
                ExchangeRate.objects
                .filter(
                    currency_from = currency,
                    currency_to   = bob,
                    market_type   = market,
                    valid_until__isnull = True,
                )
                .order_by('-valid_from')
                .first()
            )
            if rate:
                return Response({
                    'currency':     code,
                    'buy':          float(rate.buy_rate),
                    'sell':         float(rate.sell_rate),
                    'official':     float(rate.official_rate),
                    'market_type':  rate.market_type,
                    'scale_factor': currency.scale_factor,
                    'source':       rate.source or '',
                    'updated_at':   rate.valid_from.isoformat() if rate.valid_from else None,
                })

        return Response({'error': f'No active rate for {code}'}, status=404)


class ArbitrageView(viewsets.ViewSet):
    """
    GET /api/rates/arbitrage/
    Detecta oportunidades de arbitraje entre fuentes de tasas activas.

    Parámetros opcionales:
      ?type=cross_source|spread_margin|bcb_premium|triangular  — filtrar tipo
      ?min_profit=2.5  — umbral mínimo de ganancia %

    Respuesta cacheada 5 minutos. Forzar refresco con ?refresh=true.
    """
    permission_classes = [IsAuthenticated]

    def list(self, request):
        from .arbitrage import ArbitrageDetector, MIN_PROFIT_PCT

        type_filter = request.query_params.get('type')
        min_profit  = float(request.query_params.get('min_profit', MIN_PROFIT_PCT))
        force       = request.query_params.get('refresh', '').lower() == 'true'

        cache_key = f"arbitrage_{type_filter or 'all'}_{min_profit}"
        if not force:
            cached = cache.get(cache_key)
            if cached:
                return Response(cached)

        try:
            detector = ArbitrageDetector()
            data     = detector.summary()

            # Filtros opcionales
            if type_filter:
                data['opportunities'] = [
                    o for o in data['opportunities'] if o['type'] == type_filter
                ]
                data['total_opportunities'] = len(data['opportunities'])

            if min_profit != MIN_PROFIT_PCT:
                data['opportunities'] = [
                    o for o in data['opportunities'] if o['profit_pct'] >= min_profit
                ]
                data['total_opportunities'] = len(data['opportunities'])

            if data['opportunities']:
                data['best_opportunity'] = data['opportunities'][0]

            cache.set(cache_key, data, 300)
            return Response(data)

        except Exception as exc:
            import logging
            logging.getLogger('kapitalya.rates').error(
                "ARBITRAGE_VIEW_ERROR error=%s", exc, exc_info=True
            )
            return Response(
                {'error': 'Error al calcular arbitraje', 'detail': str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ExchangeRateSourceViewSet(viewsets.ModelViewSet):
    """CRUD para fuentes de tasas de cambio + acción de refresco manual."""
    queryset           = ExchangeRateSource.objects.all()
    serializer_class   = ExchangeRateSourceSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=True, methods=['POST'])
    def refresh(self, request, pk=None):
        """POST /api/rates/sources/{id}/refresh/ — fuerza actualización de esta fuente."""
        if request.user.role not in ('ADMIN', 'MANAGER'):
            return Response({'error': 'No autorizado'}, status=status.HTTP_403_FORBIDDEN)

        from .tasks import update_all_rates
        update_all_rates.delay()
        return Response({'queued': True})


class RateConfigurationViewSet(viewsets.ModelViewSet):
    queryset = RateConfiguration.objects.all()
    serializer_class = RateConfigurationSerializer
    permission_classes = [IsAuthenticated]
    
    def update(self, request, *args, **kwargs):
        """Solo administradores pueden actualizar configuraciones"""
        if request.user.role != 'ADMIN':
            return Response(
                {'error': 'No autorizado'},
                status=status.HTTP_403_FORBIDDEN
            )
        return super().update(request, *args, **kwargs)


class BinanceP2PView(APIView):
    """
    GET  /api/rates/binance/  — lee la tasa cacheada o última en DB
    POST /api/rates/binance/  — fuerza un fetch desde Binance (ADMIN)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.core.cache import cache
        cached = cache.get('binance_p2p_usd_bob')
        if cached:
            return Response({**cached,
                             'buy':  str(cached['buy']),
                             'sell': str(cached['sell']),
                             'official': str(cached['official']),
                             'from_cache': True})

        # Buscar última tasa en DB
        try:
            from .models import ExchangeRate, Currency
            usd = Currency.objects.get(code='USD')
            bob = Currency.objects.get(code='BOB')
            r = (ExchangeRate.objects
                 .filter(currency_from=usd, currency_to=bob,
                         market_type='paralelo_digital', source='binance_p2p')
                 .order_by('-valid_from').first())
            if r:
                return Response({
                    'buy':    str(r.buy_rate),
                    'sell':   str(r.sell_rate),
                    'official': str(r.official_rate),
                    'source': 'binance_p2p',
                    'from_cache': False,
                    'valid_from': r.valid_from.isoformat(),
                })
        except Exception:
            pass
        return Response({'error': 'Sin datos Binance disponibles'}, status=404)

    def post(self, request):
        if request.user.role != 'ADMIN':
            return Response({'error': 'Solo administradores pueden forzar el fetch'},
                            status=status.HTTP_403_FORBIDDEN)
        try:
            # Lanzar como tarea Celery o ejecutar directo si Celery no disponible
            try:
                from .tasks import fetch_binance_p2p_task
                fetch_binance_p2p_task.delay()
                return Response({'queued': True, 'message': 'Tarea enviada a Celery'})
            except Exception:
                from .fetchers.binance_p2p import fetch_binance_p2p
                result = fetch_binance_p2p()
                return Response({
                    **result,
                    'buy':  str(result['buy']),
                    'sell': str(result['sell']),
                    'official': str(result['official']),
                })
        except Exception as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)


class RateHistoryView(APIView):
    """
    GET /api/rates/history/
    Returns historical exchange rate data for charts.

    Query params:
        currency   — currency code (default: USD)
        days       — lookback window in days (default: 30, max: 365)
        market     — market_type filter (optional)
        granularity — 'daily' | 'hourly' (default: daily)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        currency_code = request.query_params.get('currency', 'USD')
        days = min(int(request.query_params.get('days', 30)), 365)
        market = request.query_params.get('market', '')
        granularity = request.query_params.get('granularity', 'daily')

        cache_key = f'rate_history:{currency_code}:{days}:{market}:{granularity}'
        cached = cache.get(cache_key)
        if cached:
            return Response(cached)

        try:
            currency = Currency.objects.get(code=currency_code)
        except Currency.DoesNotExist:
            return Response(
                {'error': f"Divisa '{currency_code}' no encontrada"},
                status=status.HTTP_404_NOT_FOUND,
            )

        cutoff = timezone.now() - timedelta(days=days)
        qs = ExchangeRate.objects.filter(
            currency_from=currency,
            valid_from__gte=cutoff,
        ).order_by('valid_from')

        if market:
            qs = qs.filter(market_type=market)

        # Aggregate by day or hour using valid_from (actual rate date, not import date)
        if granularity == 'hourly':
            trunc_fn = TruncHour('valid_from')
        else:
            trunc_fn = TruncDate('valid_from')

        aggregated = (
            qs
            .annotate(period=trunc_fn)
            .values('period', 'market_type')
            .annotate(
                avg_buy=Avg('buy_rate'),
                avg_sell=Avg('sell_rate'),
                avg_official=Avg('official_rate'),
                min_buy=Min('buy_rate'),
                max_sell=Max('sell_rate'),
                count=Max('id'),  # just a count proxy
            )
            .order_by('period', 'market_type')
        )

        # Also build raw point series (for sparklines)
        raw_points = list(qs.values(
            'valid_from', 'buy_rate', 'sell_rate', 'official_rate', 'market_type'
        )[:2000])

        result = {
            'currency': currency_code,
            'currency_name': currency.name_en,
            'scale_factor': currency.scale_factor,
            'days': days,
            'market': market or 'all',
            'granularity': granularity,
            'aggregated': [
                {
                    'period': r['period'].isoformat() if r['period'] else None,
                    'market_type': r['market_type'],
                    'avg_buy':  float(r['avg_buy']  or 0),
                    'avg_sell': float(r['avg_sell'] or 0),
                    'avg_official': float(r['avg_official'] or 0),
                    'min_buy':  float(r['min_buy']  or 0),
                    'max_sell': float(r['max_sell'] or 0),
                }
                for r in aggregated
            ],
            'points': [
                {
                    'ts':       p['valid_from'].isoformat(),
                    'buy':      float(p['buy_rate']  or 0),
                    'sell':     float(p['sell_rate'] or 0),
                    'official': float(p['official_rate'] or 0),
                    'market':   p['market_type'],
                }
                for p in raw_points
            ],
            'total_points': len(raw_points),
        }

        cache.set(cache_key, result, 300)  # 5-min cache
        return Response(result)


class AIPricingView(APIView):
    """
    GET  /api/rates/ai-pricing/?currency=USD  — última sugerencia de precios AI
    POST /api/rates/ai-pricing/               — calcular ahora (on-demand)

    Body POST: {"currency": "USD", "branch_id": 1}  (branch_id opcional)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from rates.models import ExchangeRateDecisionLog
        currency = request.query_params.get('currency', 'USD')
        limit    = min(int(request.query_params.get('limit', 5)), 50)

        qs = ExchangeRateDecisionLog.objects.filter(currency_code=currency).order_by('-created_at')[:limit]
        data = []
        for d in qs:
            data.append({
                'id':             d.pk,
                'currency':       d.currency_code,
                'suggested_buy':  float(d.suggested_buy),
                'suggested_sell': float(d.suggested_sell),
                'suggested_spread_pct': float(d.suggested_spread_pct),
                'base_rate':      float(d.base_rate_bob),
                'inventory_factor': float(d.inventory_factor),
                'demand_factor':   float(d.demand_factor),
                'stock_pct':       float(d.inventory_stock_pct) if d.inventory_stock_pct else None,
                'actual_buy':      float(d.actual_buy) if d.actual_buy else None,
                'actual_sell':     float(d.actual_sell) if d.actual_sell else None,
                'deviation_pct':   float(d.deviation_from_actual_pct) if d.deviation_from_actual_pct else None,
                'recommendation':  d.recommendation,
                'trigger':         d.trigger,
                'created_at':      d.created_at.isoformat(),
                'rates_used': {
                    'bcb':         float(d.rate_bcb) if d.rate_bcb else None,
                    'binance':     float(d.rate_binance) if d.rate_binance else None,
                    'historical':  float(d.rate_historical) if d.rate_historical else None,
                    'competition': float(d.rate_competition) if d.rate_competition else None,
                },
            })
        return Response({'currency': currency, 'decisions': data, 'count': len(data)})

    def post(self, request):
        currency  = request.data.get('currency', 'USD')
        branch_id = request.data.get('branch_id')

        branch = None
        if branch_id:
            try:
                from users.models import Branch
                branch = Branch.objects.get(pk=branch_id)
            except Exception:
                return Response({'error': f'Branch {branch_id} not found'}, status=400)

        try:
            from rates.ai_pricing import AIPricingEngine
            engine = AIPricingEngine()
            result = engine.suggest_and_save(currency, branch=branch, trigger='manual')
            result['decision_id'] = result.get('decision_id')
            return Response({
                'currency':        currency,
                'suggested_buy':   float(result['suggested_buy']),
                'suggested_sell':  float(result['suggested_sell']),
                'suggested_spread_pct': float(result['suggested_spread_pct']),
                'base_rate':       float(result['base_rate']),
                'inventory_factor': float(result['inventory_factor']),
                'demand_factor':    float(result['demand_factor']),
                'recommendation':   result['recommendation'],
                'rates_used':       result['rates_used'],
                'weights_used':     result['weights_used'],
                'inventory':        result['inventory'],
                'demand':           result['demand'],
                'decision_id':      result.get('decision_id'),
            })
        except ValueError as exc:
            return Response({'error': str(exc)}, status=400)
        except Exception as exc:
            import logging
            logging.getLogger('kapitalya.rates').exception('AIPricingView POST error')
            return Response({'error': str(exc)}, status=500)


class ForecastView(APIView):
    """
    GET /api/rates/forecast/?currency=USD&days=14

    Retorna predicciones de TC para los próximos N días usando Prophet.
    También devuelve el histórico de los últimos 30 días para el gráfico.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from predictions.models import Prediction
        from rates.models import ExchangeRate, Currency

        currency_code = request.query_params.get('currency', 'USD')
        days          = min(int(request.query_params.get('days', 14)), 30)

        cache_key = f'forecast:{currency_code}:{days}'
        cached    = cache.get(cache_key)
        if cached:
            return Response(cached)

        # Obtener predicciones de los próximos N días
        now = timezone.now()
        forecasts = (Prediction.objects
                     .filter(
                         currency_pair__startswith=currency_code,
                         prediction_date__gte=now,
                         prediction_date__lte=now + timedelta(days=days),
                     )
                     .order_by('prediction_date')
                     .values('prediction_date', 'predicted_buy_rate', 'predicted_sell_rate',
                             'confidence_lower', 'confidence_upper', 'confidence_score')[:days * 24])

        # Histórico real últimos 30 días
        try:
            cur = Currency.objects.get(code=currency_code)
            bob = Currency.objects.get(code='BOB')
            historical = (ExchangeRate.objects
                          .filter(currency_from=cur, currency_to=bob,
                                  market_type__in=('paralelo_fisico_empresa', 'paralelo_digital'),
                                  valid_from__gte=now - timedelta(days=30))
                          .order_by('valid_from')
                          .values('valid_from', 'buy_rate', 'sell_rate')[:300])
        except Exception:
            historical = []

        result = {
            'currency':   currency_code,
            'days':       days,
            'historical': [
                {'date': p['valid_from'].isoformat(), 'buy': float(p['buy_rate']),
                 'sell': float(p['sell_rate'])}
                for p in historical
            ],
            'forecast': [
                {
                    'date':       p['prediction_date'].isoformat(),
                    'buy':        float(p['predicted_buy_rate']),
                    'sell':       float(p['predicted_sell_rate']),
                    'lower':      float(p['confidence_lower']),
                    'upper':      float(p['confidence_upper']),
                    'confidence': float(p['confidence_score']),
                }
                for p in forecasts
            ],
            'has_forecast': len(list(forecasts)) > 0,
        }

        cache.set(cache_key, result, 1800)  # 30 min
        return Response(result)


class EngineView(viewsets.ViewSet):
    """
    Motor central de tasas — endpoints de gestión del sistema de tasas unificado.

    GET  /api/rates/engine/primary/      — tasas primarias de todas las divisas
    GET  /api/rates/engine/summary/      — estadísticas multi-fuente por divisa
    GET  /api/rates/engine/divergences/  — detección de divergencias entre fuentes
    POST /api/rates/engine/refresh/      — fuerza actualización de todas las fuentes (ADMIN)
    """
    permission_classes = [AllowAny]

    def primary(self, request):
        """
        GET /api/rates/engine/primary/
        Tasas primarias (is_primary=True) activas para todas las divisas.
        Estas son las tasas que usa el sistema en transacciones.
        ?currency=USD  — filtra a una sola divisa
        """
        from .exchange_rate_service import ExchangeRateService

        currency_filter = request.query_params.get('currency')
        service         = ExchangeRateService()

        currencies = Currency.objects.filter(is_active=True).exclude(code='BOB')
        if currency_filter:
            currencies = currencies.filter(code=currency_filter.upper())

        result = {}
        for cur in currencies:
            rate = service.get_primary_rate(cur.code)
            if not rate:
                continue
            result[cur.code] = {
                'currency_from':   cur.code,
                'currency_to':     'BOB',
                'scale_factor':    cur.scale_factor,
                'buy_rate':        str(rate.buy_rate),
                'sell_rate':       str(rate.sell_rate),
                'official_rate':   str(rate.official_rate),
                'avg_rate':        str(rate.avg_rate or (rate.buy_rate + rate.sell_rate) / Decimal('2')),
                'source_method':   rate.source_method,
                'source_url':      rate.source_url,
                'market_type':     rate.market_type,
                'confidence':      float(rate.confidence),
                'fetched_at':      rate.fetched_at.isoformat() if rate.fetched_at else None,
                'is_validated':    rate.is_validated,
                'is_primary':      rate.is_primary,
                'requires_warning': rate.requires_warning,
                'is_safe_for_transaction': (
                    rate.source_method != 'INFERENCE'
                    and float(rate.confidence) >= 0.70
                ),
                'updated_at':      rate.valid_from.isoformat() if rate.valid_from else None,
            }

        return Response({
            'rates':       result,
            'count':       len(result),
            'generated_at': timezone.now().isoformat(),
        })

    def summary(self, request):
        """
        GET /api/rates/engine/summary/?currency=USD
        Resumen multi-fuente: tasa primaria, estadísticas y comparación por fuente.
        """
        from .exchange_rate_service import ExchangeRateService

        currency_code = request.query_params.get('currency', 'USD')
        force_refresh = request.query_params.get('refresh', '').lower() == 'true'

        service = ExchangeRateService()
        summary = service.get_rates_summary(currency_code, force_refresh=force_refresh)
        if not summary:
            return Response(
                {'error': f'No hay tasas activas para {currency_code}/BOB'},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(summary.to_dict())

    def divergences(self, request):
        """
        GET /api/rates/engine/divergences/?threshold=5.0
        Detecta inconsistencias entre fuentes. Alerta si desviación > threshold%.
        """
        from .exchange_rate_service import ExchangeRateService

        try:
            threshold = float(request.query_params.get('threshold', 5.0))
        except ValueError:
            threshold = 5.0

        service = ExchangeRateService()
        result  = service.detect_divergences(threshold_pct=threshold)
        return Response({
            'threshold_pct':    threshold,
            'divergence_count': len(result),
            'divergences':      result,
            'has_alerts':       any(d['severity'] == 'CRITICAL' for d in result),
            'checked_at':       timezone.now().isoformat(),
        })

    def refresh(self, request):
        """
        POST /api/rates/engine/refresh/
        Fuerza actualización de TODAS las fuentes (BCB, DolarApi, BCP, Binance, scraping).
        Solo ADMIN. Responde inmediatamente; las actualizaciones se hacen async.
        """
        if not request.user.is_authenticated or request.user.role != 'ADMIN':
            return Response({'error': 'Solo administradores pueden forzar el refresco'},
                            status=status.HTTP_403_FORBIDDEN)

        from .tasks import update_all_rates, mark_primary_rates_task, fetch_binance_p2p_task
        update_all_rates.delay()
        fetch_binance_p2p_task.delay()
        mark_primary_rates_task.delay()

        return Response({
            'queued':  True,
            'message': 'Actualización de todas las fuentes encolada. Las tasas se actualizarán en ~30 segundos.',
            'tasks':   ['update_all_rates', 'fetch_binance_p2p', 'mark_primary_rates'],
        })


# ── Auto Profit Mode ──────────────────────────────────────────────────────────

class ProfitOptimizerView(APIView):
    """
    GET  /api/rates/profit-optimizer/?currency=USD&variant=USD_CASH_LOOSE
         Calcula tasas óptimas para la divisa indicada usando el mercado actual.

    POST /api/rates/profit-optimizer/
         Body: { currency, variant?, max_buy_discount_pct?, max_sell_premium_pct?,
                 min_spread_bob?, max_spread_pct? }
         Calcula con parámetros customizados.

    GET  /api/rates/profit-optimizer/all/
         Calcula tasas óptimas para TODAS las divisas activas + variantes físicas.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        currency = request.query_params.get('currency', 'USD').upper()
        variant  = request.query_params.get('variant') or None
        all_mode = request.query_params.get('all', '').lower() == 'true'

        try:
            from .profit_optimizer import ProfitOptimizer
            optimizer = ProfitOptimizer()

            if all_mode:
                results = optimizer.optimize_all(include_variants=True)
                return Response({
                    'optimized_rates': {
                        (r.variant or r.currency_code): r.to_dict()
                        for r in results.values()
                    },
                    'currency_count': len(results),
                    'calculated_at':  timezone.now().isoformat(),
                })

            result = optimizer.optimize(currency, variant=variant)
            return Response(result.to_dict())

        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response({'error': f'Error del optimizador: {exc}'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    def post(self, request):
        data = request.data

        currency     = data.get('currency', 'USD').upper()
        variant      = data.get('variant') or None
        market_buy   = data.get('market_buy')
        market_sell  = data.get('market_sell')

        from decimal import Decimal as _D, InvalidOperation
        try:
            params = {}
            for key in ('max_buy_discount_pct', 'max_sell_premium_pct', 'min_spread_bob', 'max_spread_pct'):
                if key in data:
                    params[key] = _D(str(data[key]))

            market_buy_d  = _D(str(market_buy))  if market_buy  else None
            market_sell_d = _D(str(market_sell)) if market_sell else None

            from .profit_optimizer import ProfitOptimizer
            optimizer = ProfitOptimizer(**params)
            result    = optimizer.optimize(
                currency,
                variant      = variant,
                market_buy   = market_buy_d,
                market_sell  = market_sell_d,
            )
            return Response(result.to_dict())

        except (ValueError, InvalidOperation) as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response({'error': f'Error del optimizador: {exc}'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


# ── Cash Variants ─────────────────────────────────────────────────────────────

class CashVariantsView(APIView):
    """
    GET  /api/rates/cash-variants/
         Lista todas las variantes de efectivo con sus tasas calculadas.

    POST /api/rates/cash-variants/refresh/
         Recalcula y persiste tasas de variantes (requiere ADMIN o MANAGER).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        refresh = request.query_params.get('refresh', 'false').lower() == 'true'

        cache_key = 'cash_variants_all'
        if not refresh:
            cached = cache.get(cache_key)
            if cached:
                return Response({**cached, 'from_cache': True})

        try:
            from .cash_variants import CashVariantService, VARIANT_CONFIG
            service = CashVariantService()
            rates   = service.calculate_all()

            payload = {
                'variants':        {code: r.to_dict() for code, r in rates.items()},
                'variant_count':   len(rates),
                'variant_config':  {
                    code: {
                        'name_es':          cfg['name_es'],
                        'description':      cfg['description'],
                        'icon':             cfg['icon'],
                        'base_currency':    cfg['base_currency'],
                        'buy_discount_pct': float(cfg['buy_discount_pct']),
                    }
                    for code, cfg in VARIANT_CONFIG.items()
                },
                'calculated_at':   timezone.now().isoformat(),
                'from_cache':      False,
            }
            cache.set(cache_key, payload, 300)  # 5 min cache
            return Response(payload)

        except Exception as exc:
            return Response({'error': str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    def post(self, request):
        if not request.user.is_authenticated or getattr(request.user, 'role', '') not in ('ADMIN', 'MANAGER'):
            return Response({'error': 'Requiere rol ADMIN o MANAGER'}, status=status.HTTP_403_FORBIDDEN)

        try:
            from .tasks import update_cash_variants_task
            update_cash_variants_task.delay()
            cache.delete('cash_variants_all')
            return Response({
                'queued':  True,
                'message': 'Recálculo de variantes de efectivo encolado.',
            })
        except Exception as exc:
            return Response({'error': str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


# ── Rate Snapshots ────────────────────────────────────────────────────────────

class RateSnapshotView(APIView):
    """
    GET /api/rates/snapshots/?days=30        → lista de snapshots
    GET /api/rates/snapshots/?date=2026-04-28 → snapshot específico
    POST /api/rates/snapshots/create/         → forzar creación del snapshot de hoy
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .models import ExchangeRateSnapshot

        date_str = request.query_params.get('date')
        days     = int(request.query_params.get('days', 30))

        if date_str:
            try:
                from datetime import date
                snap = ExchangeRateSnapshot.objects.get(date=date_str)
                return Response(self._serialize_snapshot(snap))
            except ExchangeRateSnapshot.DoesNotExist:
                return Response({'error': f'Sin snapshot para {date_str}'}, status=status.HTTP_404_NOT_FOUND)
            except Exception as exc:
                return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        cutoff = timezone.now().date() - timedelta(days=days)
        snaps  = (ExchangeRateSnapshot.objects
                  .filter(date__gte=cutoff)
                  .order_by('-date')[:days])

        return Response({
            'snapshots':    [self._serialize_snapshot(s) for s in snaps],
            'count':        len(snaps),
            'days_requested': days,
        })

    def post(self, request):
        if not request.user.is_authenticated or getattr(request.user, 'role', '') not in ('ADMIN', 'MANAGER'):
            return Response({'error': 'Requiere rol ADMIN o MANAGER'}, status=status.HTTP_403_FORBIDDEN)

        from .tasks import create_daily_snapshot_task
        create_daily_snapshot_task.delay()
        return Response({'queued': True, 'message': 'Snapshot diario encolado.'})

    @staticmethod
    def _serialize_snapshot(snap) -> dict:
        return {
            'id':            snap.pk,
            'date':          str(snap.date),
            'status':        snap.status,
            'best_source':   snap.best_source,
            'avg_usd_buy':   float(snap.avg_usd_buy)  if snap.avg_usd_buy  else None,
            'avg_usd_sell':  float(snap.avg_usd_sell) if snap.avg_usd_sell else None,
            'max_spread_pct': float(snap.max_spread_pct) if snap.max_spread_pct else None,
            'source_count':  snap.source_count,
            'anomaly_count': snap.anomaly_count,
            'close_usd_buy':  float(snap.close_usd_buy)  if snap.close_usd_buy  else None,
            'close_usd_sell': float(snap.close_usd_sell) if snap.close_usd_sell else None,
            'aggregated_data': snap.aggregated_data,
            'notes':         snap.notes,
            'created_at':    snap.created_at.isoformat(),
        }


# ─────────────────────────────────────────────────────────────────────────────
#  Reference Rate Panel — BCB / BCP display only
# ─────────────────────────────────────────────────────────────────────────────

class ReferenceRateView(APIView):
    """
    GET  /api/rates/reference/         — all latest reference rates
    GET  /api/rates/reference/?currency=USD&source=BCB
    POST /api/rates/reference/refresh/ — trigger fetch (ADMIN only)

    ⚠️  Valor referencial solamente — no usado para operaciones.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        from .models import ReferenceRate
        from .serializers import ReferenceRateSerializer
        from .fetchers.reference_fetcher import get_latest_reference

        currency = request.query_params.get('currency', 'USD').upper()
        source   = request.query_params.get('source')

        # Return latest record per source
        qs = ReferenceRate.objects.filter(currency=currency)
        if source:
            qs = qs.filter(source=source.upper())

        # One record per source (most recent)
        seen_sources: set[str] = set()
        records = []
        for obj in qs.order_by('source', '-timestamp'):
            if obj.source not in seen_sources:
                seen_sources.add(obj.source)
                records.append(obj)

        serializer = ReferenceRateSerializer(records, many=True)

        return Response({
            'currency':   currency,
            'note':       'Valor referencial del dólar estadounidense — solo referencia, no usado para operaciones',
            'label':      'Solo referencia - no usado para operaciones',
            'references': serializer.data,
        })


class ReferenceRateRefreshView(APIView):
    """POST /api/rates/reference/refresh/ — triggers BCB/BCP fetch."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if getattr(request.user, 'role', '') not in ('ADMIN', 'MANAGER'):
            return Response(
                {'error': 'Requiere rol ADMIN o MANAGER'},
                status=status.HTTP_403_FORBIDDEN,
            )
        from .tasks import fetch_reference_rates_task
        fetch_reference_rates_task.delay()
        return Response({'queued': True, 'message': 'Actualización de tasas de referencia encolada.'})


# ─────────────────────────────────────────────────────────────────────────────
#  FX Engine View — production parallel market rates
# ─────────────────────────────────────────────────────────────────────────────

class FXEngineView(APIView):
    """
    GET  /api/rates/fx-engine/         — latest 2-decimal rates from parallel market
    GET  /api/rates/fx-engine/?refresh=true — force engine run (ADMIN only)
    POST /api/rates/fx-engine/run/     — trigger full engine run (ADMIN only)

    Returns rates based ONLY on parallel market P2P data.
    All values are rounded to 2 decimal places.
    Cash variants (USD_LOOSE, USD_SMALL, PEN_COINS) included.
    """
    permission_classes = [AllowAny]
    CACHE_KEY = 'fx_engine_latest'
    CACHE_TTL = 120   # 2 minutes

    def get(self, request):
        from .fx_engine import get_live_rates, run_engine, CASH_VARIANT_ADJUSTMENTS
        from .fetchers.reference_fetcher import get_latest_reference

        force_refresh = request.query_params.get('refresh', '').lower() == 'true'

        if force_refresh and request.user.is_authenticated:
            result = run_engine(save=True, emit=True)
            rates  = {code: r.to_dict() for code, r in result.all_rates().items()}
        else:
            rates = cache.get(self.CACHE_KEY)
            if not rates:
                rates = get_live_rates()
                if rates:
                    cache.set(self.CACHE_KEY, rates, self.CACHE_TTL)

        # Attach reference rates (display panel)
        reference = get_latest_reference('USD')

        return Response({
            'rates':     rates,
            'variants':  {k: v for k, v in rates.items() if k in CASH_VARIANT_ADJUSTMENTS},
            'reference': reference,
            'precision': 2,
            'note':      'Tasas basadas exclusivamente en mercado paralelo (P2P)',
        })

    def post(self, request):
        if not request.user.is_authenticated or getattr(request.user, 'role', '') not in ('ADMIN', 'MANAGER'):
            return Response(
                {'error': 'Requiere rol ADMIN o MANAGER'},
                status=status.HTTP_403_FORBIDDEN,
            )
        from .tasks import run_fx_engine_task
        run_fx_engine_task.delay()
        return Response({'queued': True, 'message': 'FX Engine encolado para ejecución.'})
