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
from core.cache_decorators import cache_response
from .models import Currency, ExchangeRate, ExchangeRateSource, RateConfiguration
from core.ratelimit import rate_limit
from .serializers import (
    CurrencySerializer, ExchangeRateSerializer,
    ExchangeRateSourceSerializer, RateConfigurationSerializer,
)

def _live_historical_fallback(currency: str, engine=None):
    """
    Último recurso cuando el engine no encuentra ninguna fuente en tiempo real.
    Lee la tasa más reciente en DB para la divisa (incluyendo tasas expiradas)
    y la devuelve como RateResult con is_live=False y confianza degradada.
    """
    from decimal import Decimal
    from rates.engine import RateEngine, RateResult
    from rates.models import Currency, ExchangeRate

    log = __import__('logging').getLogger('kapitalya.rates.engine')
    try:
        cur = Currency.objects.get(code=currency)
        bob = Currency.objects.get(code='BOB')
        rate = (
            ExchangeRate.objects
            .filter(currency_from=cur, currency_to=bob)
            .order_by('-valid_from')
            .first()
        )
        if not rate:
            return None
        age_minutes = (timezone.now() - rate.valid_from).total_seconds() / 60
        log.warning(
            'ENGINE_HISTORICAL_FALLBACK currency=%s source=%s age_min=%.0f',
            currency, rate.source, age_minutes,
        )
        _engine = engine or RateEngine()
        return _engine._build_result(
            currency   = currency,
            buy        = rate.buy_rate,
            sell       = rate.sell_rate,
            source     = f'historical:{rate.source or "db"}',
            source_url = rate.source_url,
            confidence = Decimal(str(rate.confidence)) * Decimal('0.70'),
            timestamp  = rate.fetched_at or rate.valid_from,
            is_live    = False,
        )
    except Exception as exc:
        log.error('ENGINE_HISTORICAL_FALLBACK_ERROR currency=%s error=%s', currency, exc)
        return None


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

    @action(detail=False, methods=['GET'], permission_classes=[AllowAny], url_path='sources-live')
    def sources_live(self, request):
        """
        Retorna tasas en tiempo real por plataforma para una divisa.

        ?currency=USD    (default USD)
        ?refresh=true    fuerza nuevo fetch (ignora caché)

        Estrategia:
          1. Sirve desde caché Redis (TTL 5 min) si está disponible.
          2. En caché miss: ejecuta fetchers en paralelo (ThreadPoolExecutor, timeout 15s).
          3. Filtra FetchResult por currency_code pedido.
          4. Devuelve array de fuentes con compra/venta/confianza/método/antigüedad.
        """
        import concurrent.futures
        import logging

        log = logging.getLogger('kapitalya.rates.sources_live')

        currency_code = request.query_params.get('currency', 'USD').upper()
        force_refresh = request.query_params.get('refresh', '').lower() == 'true'

        cache_key = f'sources_live_v3_{currency_code}'
        if not force_refresh:
            cached = cache.get(cache_key)
            if cached is not None:
                return Response(cached)

        # ── Select fetchers relevant to this currency ─────────────────────────
        from .fetchers.p2p_exchanges              import BinanceP2PFetcher, BitgetP2PFetcher, BybitP2PFetcher
        from .fetchers.dolar_blue_bolivia         import DolarBlueBoliviaFetcher
        from .fetchers.eldorado_fetcher           import EldoradoFetcher
        from .fetchers.wallbit_fetcher            import WallbitFetcher
        from .fetchers.saldoar_fetcher            import SaldoARFetcher
        from .fetchers.airtm_v2_fetcher           import AirtmQuoteFetcher
        from .fetchers.okx_fetcher                import OKXFetcher
        from .fetchers.p2p_multi_fiat             import BinanceCrossRateFetcher, all_binance_cross_fetchers
        from .fetchers.dolaresabolivianos_fetcher import DolaresABolivianosLLMFetcher, DolaresABolivianosLastFetcher
        from .fetchers.criptoya_fetcher           import CriptoYaBOBFetcher, CriptoYaCrossRateFetcher, all_criptoya_cross_fetchers
        from .fetchers.dolarapi_bolivia_fetcher   import DolarApiBoliviaOficialFetcher, DolarApiBoliviaListFetcher

        if currency_code == 'USD':
            fetchers = [
                BinanceP2PFetcher(),
                BitgetP2PFetcher(),
                BybitP2PFetcher(),
                OKXFetcher(),
                DolarBlueBoliviaFetcher(),
                EldoradoFetcher(),
                WallbitFetcher(),
                SaldoARFetcher(),
                AirtmQuoteFetcher(),
                DolaresABolivianosLLMFetcher(),
                DolaresABolivianosLastFetcher(),
                CriptoYaBOBFetcher(),
                DolarApiBoliviaOficialFetcher(),
                DolarApiBoliviaListFetcher(),
            ]
        elif currency_code in ('ARS', 'CLP', 'PEN', 'BRL'):
            fetchers = [
                BinanceCrossRateFetcher(currency_code),
                CriptoYaCrossRateFetcher(currency_code),
                DolarBlueBoliviaFetcher(),
            ]
        elif currency_code == 'EUR':
            fetchers = [
                BinanceCrossRateFetcher(currency_code),
                DolarBlueBoliviaFetcher(),
            ]
        else:
            fetchers = [DolarBlueBoliviaFetcher()]

        # ── Run in parallel ────────────────────────────────────────────────────
        all_fetch_results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            futures = {pool.submit(f.fetch): f.source_name for f in fetchers}
            done, _ = concurrent.futures.wait(futures, timeout=25)
            for fut in done:
                try:
                    all_fetch_results.extend(fut.result() or [])
                except Exception as exc:
                    log.warning('sources_live fetch error: %s', exc)

        # ── Human-readable labels ──────────────────────────────────────────────
        SOURCE_LABELS: dict[str, str] = {
            'BINANCE_P2P':        'Binance P2P',
            'BITGET_P2P':         'Bitget P2P',
            'BYBIT_P2P':          'Bybit P2P',
            'OKX_P2P':            'OKX P2P',
            'BINANCE_ARS':        'Binance P2P / ARS',
            'BINANCE_CLP':        'Binance P2P / CLP',
            'BINANCE_PEN':        'Binance P2P / PEN',
            'BINANCE_BRL':        'Binance P2P / BRL',
            'BINANCE_EUR':        'Binance P2P / EUR',
            'DOLARBLUE_BO':       'dolarbluebolivia.click',
            'DOLARBLUE_ELDORADO': 'El Dorado',
            'DOLARBLUE_TAKENOS':  'Takenos',
            'DOLARBLUE_WALLBIT':  'Wallbit',
            'DOLARBLUE_AIRTM':    'Airtm',
            'DOLARBLUE_BINANCE':  'Binance (referencia)',
            'DOLARBLUE_BYBIT':    'Bybit (referencia)',
            'DOLARBLUE_SALDOAR':  'SaldoAR',
            'DOLARBLUE_BITGET':   'Bitget (via dolarbluebolivia)',
            'DOLARBLUE_MERU':     'Meru (via dolarbluebolivia)',
            'DOLARBLUE_BRL':      'BRL / BOB',
            'DOLARBLUE_ARS':      'ARS / BOB',
            'DOLARBLUE_PEN':      'PEN / BOB',
            'DOLARBLUE_EUR':      'EUR / BOB',
            'DOLARBLUE_GBP':      'GBP / BOB',
            'DOLARBLUE_CLP':      'CLP / BOB',
            'DOLARBLUE_CNY':      'CNY / BOB',
            'AIRTM':                      'Airtm',
            'AIRTM_QUOTE':                'Airtm Quote',
            'ELDORADO':                   'El Dorado (directo)',
            'WALLBIT':                    'Wallbit (directo)',
            'SALDOAR':                    'SaldoAR (directo)',
            'DOLARESABOLIVIANOS_LLM':     'DólaresABolivianos',
            'DOLARESABOLIVIANOS_LAST':    'DólaresABolivianos (último)',
            'CRIPTOYA_BOB':               'CriptoYa USDT/BOB',
            'CRIPTOYA_ARS':               'CriptoYa ARS/BOB',
            'CRIPTOYA_CLP':               'CriptoYa CLP/BOB',
            'CRIPTOYA_PEN':               'CriptoYa PEN/BOB',
            'CRIPTOYA_BRL':               'CriptoYa BRL/BOB',
            'DOLARAPI_OFICIAL':           'DolarApi Bolivia (oficial)',
            'DOLARAPI_TARJETA':           'DolarApi Bolivia (tarjeta)',
            'DOLARAPI_BLUE':              'DolarApi Bolivia (blue)',
            'DOLARAPI_PARALELO':          'DolarApi Bolivia (paralelo)',
            'DOLARAPI_LISTA':             'DolarApi Bolivia',
        }

        # ── Persist raw results to ExchangeRateRaw (ML archive) ──────────────
        try:
            from .aggregator import RateAggregator
            RateAggregator().save_raw_to_db(all_fetch_results)
        except Exception as _raw_exc:
            log.warning('sources_live RAW_SAVE_ERROR: %s', _raw_exc)

        # ── Filter + format ────────────────────────────────────────────────────
        now = timezone.now()
        stale_minutes = 30
        stale_td = timedelta(minutes=stale_minutes)

        seen: set[str] = set()
        sources_out = []
        for r in all_fetch_results:
            if r.currency_code != currency_code:
                continue
            src = r.source_name.upper()
            if src in seen:
                continue
            seen.add(src)

            fetched_at = r.fetched_at
            is_stale   = (now - fetched_at) > stale_td if fetched_at else True

            sources_out.append({
                'source':        src,
                'source_label':  SOURCE_LABELS.get(src, src.replace('_', ' ').title()),
                'currency':      currency_code,
                'buy_rate':      str(r.buy_rate),
                'sell_rate':     str(r.sell_rate),
                'official_rate': str(r.official_rate),
                'confidence':    float(r.confidence),
                'source_method': r.source_method,
                'market_type':   r.market_type,
                'fetched_at':    fetched_at.isoformat() if fetched_at else None,
                'is_stale':      is_stale,
                'is_primary':    False,
                'source_url':    r.source_url,
            })

        # Sort by confidence desc
        sources_out.sort(key=lambda x: -x['confidence'])

        payload = {
            'currency':   currency_code,
            'count':      len(sources_out),
            'checked_at': now.isoformat(),
            'sources':    sources_out,
        }
        cache.set(cache_key, payload, 300)  # 5 min cache
        return Response(payload)

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
    @rate_limit(requests=10, window=60, scope='user')
    def update_rates(self, request):
        """Dispara actualización de tasas del mercado paralelo."""
        if request.user.role != 'ADMIN':
            return Response(
                {'error': 'Solo administradores pueden actualizar tasas'},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            from .tasks import fetch_dolar_blue_task, mark_primary_rates_task
            fetch_dolar_blue_task.delay()
            mark_primary_rates_task.delay()
            return Response({
                'success': True,
                'message': 'Actualización del mercado paralelo iniciada',
                'timestamp': timezone.now(),
            })
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['POST'], permission_classes=[AllowAny])
    @rate_limit(requests=60, window=60, scope='ip')
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
            rate = _live_historical_fallback(currency, engine)
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
    priorizando: paralelo_digital > parallel > digital > competencia.

    Opcionalmente acepta ?market=paralelo_digital|parallel|digital para filtrar
    por tipo de mercado.

    Formato de respuesta:
      {
        "USD": {"buy": 9.30, "sell": 9.60, "mid": 9.45,
                "market_type": "paralelo_digital", "scale_factor": 1,
                "sources": ["DOLAR_BLUE_BO"], "updated_at": "..."},
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
    @rate_limit(requests=10, window=60, scope='user')
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
                    # 'bcb' eliminado: el campo ya no existe en el modelo
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

        reference = None

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


# ════════════════════════════════════════════════════════════════════════════
# B1 / B2 / B3 — Tasa paralela, spread dinámico, rentabilidad
# ════════════════════════════════════════════════════════════════════════════

class ParallelRateView(APIView):
    """
    GET /api/rates/parallel-rate/?currency=USD&refresh=false
    Retorna la tasa paralela de consenso (media Winsorizada ponderada).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        currency = request.query_params.get('currency', 'USD').upper()
        force    = request.query_params.get('refresh', '').lower() in ('1', 'true')

        from .parallel_rate_service import ParallelRateService
        svc    = ParallelRateService()
        result = svc.get_rate(currency, force_refresh=force)

        return Response({
            'currency':       result.currency,
            'consensus_rate': str(result.consensus_rate),
            'buy_rate':       str(result.buy_rate),
            'sell_rate':      str(result.sell_rate),
            'source_count':   result.source_count,
            'confidence':     str(result.confidence),
            'is_degraded':    result.is_degraded,
            'computed_at':    result.computed_at,
            'sources': [
                {
                    'name':   s.get('name'),
                    'rate':   str(s.get('rate', '')),
                    'weight': str(s.get('weight', '')),
                }
                for s in (result.sources or [])
            ],
        })


class DynamicSpreadView(APIView):
    """
    GET /api/rates/dynamic-spread/
    Calcula buy/sell dinámicos con factores de spread.

    Query params:
      currency            — código divisa (USD)
      transaction_type    — BUY | SELL | BOTH (default BOTH)
      branch_id           — int
      customer_tier       — REGULAR | FREQUENT | VIP
      transaction_size_bob— int
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        currency     = request.query_params.get('currency', 'USD').upper()
        tx_type      = request.query_params.get('transaction_type', 'BOTH').upper()
        branch_id    = request.query_params.get('branch_id') or getattr(request.user, 'branch_id', None)
        tier         = request.query_params.get('customer_tier', 'REGULAR').upper()
        size_bob_str = request.query_params.get('transaction_size_bob')
        size_bob     = int(size_bob_str) if size_bob_str else None

        from .parallel_rate_service import ParallelRateService
        from .spread_engine import DynamicSpreadEngine

        par_result   = ParallelRateService().get_rate(currency)
        if not par_result.consensus_rate:
            return Response(
                {'error': f'No hay tasa paralela disponible para {currency}'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        branch = None
        if branch_id:
            try:
                from users.models import Branch
                branch = Branch.objects.get(pk=branch_id)
            except Exception:
                pass

        result = DynamicSpreadEngine().calculate(
            currency=currency,
            parallel_rate=par_result.consensus_rate,
            transaction_type=tx_type,
            branch=branch,
            customer_tier=tier,
            transaction_size_bob=size_bob,
        )

        return Response({
            'currency':           currency,
            'parallel_rate':      str(result.parallel_rate),
            'buy_rate':           str(result.buy_rate),
            'sell_rate':          str(result.sell_rate),
            'spread_abs':         str(result.spread_abs),
            'spread_pct':         str(result.spread_pct),
            'margin_per_1000':    str(result.margin_per_1000),
            'expires_at':         result.expires_at,
            'recommendation':     result.recommendation,
            'factors_breakdown':  result.factors_breakdown,
        })


class ProfitabilityAnalysisView(APIView):
    """
    GET /api/rates/profitability-analysis/
    Reporte de rentabilidad por período.

    Query params:
      start       — YYYY-MM-DD  (default: primer día del mes actual)
      end         — YYYY-MM-DD  (default: hoy)
      branch_id   — int
      threshold   — Decimal, umbral mínimo de margen por TX en BOB (default 50)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.utils.dateparse import parse_date
        from django.utils import timezone
        from .profitability import ProfitabilityAnalyzer
        from decimal import Decimal

        today   = timezone.localdate()
        default_start = today.replace(day=1)

        start_str = request.query_params.get('start')
        end_str   = request.query_params.get('end')
        start     = parse_date(start_str) if start_str else default_start
        end       = parse_date(end_str)   if end_str   else today

        if not start or not end or start > end:
            return Response({'error': 'Fechas inválidas'}, status=status.HTTP_400_BAD_REQUEST)

        branch_id = request.query_params.get('branch_id')
        try:
            branch_id = int(branch_id) if branch_id else getattr(request.user, 'branch_id', None)
        except ValueError:
            return Response({'error': 'branch_id inválido'}, status=status.HTTP_400_BAD_REQUEST)

        threshold_str = request.query_params.get('threshold', '50')
        try:
            threshold = Decimal(threshold_str)
        except Exception:
            threshold = Decimal('50')

        company_id = getattr(request.user, 'company_id', None)
        if not company_id:
            return Response({'error': 'Usuario sin company_id'}, status=status.HTTP_400_BAD_REQUEST)

        report = ProfitabilityAnalyzer().analyze(
            company_id=company_id,
            date_from=start,
            date_to=end,
            branch_id=branch_id,
            min_margin_threshold=threshold,
        )

        return Response({
            'period_start':         report.period_start,
            'period_end':           report.period_end,
            'total_transactions':   report.total_transactions,
            'total_volume_foreign': str(report.total_volume_foreign),
            'total_margin_bob':     str(report.total_margin_bob),
            'avg_margin_pct':       str(report.avg_margin_pct),
            'by_currency_pair':     report.by_currency_pair,
            'by_cashier':           report.by_cashier,
            'by_hour':              report.by_hour,
            'by_customer_segment':  report.by_customer_segment,
            'alert_count':          len(report.alerts),
            'alerts':               report.alerts[:20],
        })


# ─────────────────────────────────────────────────────────────────────────────
#  Integration layer API — /api/v1/rates/consensus/ etc.
# ─────────────────────────────────────────────────────────────────────────────

class ConsensusView(APIView):
    """
    GET /api/v1/rates/consensus/
    Tasas de consenso vigentes para todos los pares.

    Response:
    {
      "timestamp": "…",
      "tasas": {
        "USD/BOB": {"compra": 9.90, "venta": 9.70, "consenso": 9.82,
                    "fuentes": 8, "confianza": 91, "tendencia": "ALCISTA",
                    "cambio_pct_24h": 0.51},
        …
      }
    }
    """
    permission_classes = [AllowAny]
    CACHE_KEY = 'integration_consensus_all'
    CACHE_TTL = 60

    def get(self, request):
        force = request.query_params.get('refresh', '').lower() == 'true'
        if not force:
            cached = cache.get(self.CACHE_KEY)
            if cached:
                return Response(cached)

        from .models import ExchangeRateConsensus
        vigentes = (
            ExchangeRateConsensus.objects
            .filter(vigente=True)
            .order_by('par')
        )

        tasas = {}
        for c in vigentes:
            tasas[c.par] = {
                'compra':        float(c.precio_compra)  if c.precio_compra  else None,
                'venta':         float(c.precio_venta)   if c.precio_venta   else None,
                'consenso':      float(c.precio_consenso),
                'fuentes':       c.fuentes_count,
                'confianza':     c.confianza_pct,
                'tendencia':     c.tendencia or 'NEUTRAL',
                'cambio_pct_24h': float(c.cambio_pct_24h) if c.cambio_pct_24h else 0.0,
                'metodo':        c.metodo_calculo,
                'actualizado':   c.timestamp_calculo.isoformat(),
            }

        payload = {
            'timestamp': timezone.now().isoformat(),
            'pares':     len(tasas),
            'tasas':     tasas,
        }
        cache.set(self.CACHE_KEY, payload, self.CACHE_TTL)
        return Response(payload)


class RawHistoryView(APIView):
    """
    GET /api/v1/rates/history/
    Serie de tiempo de datos crudos para un par específico.

    Params:
      par      — "USD/BOB" (requerido)
      desde    — ISO date (default: hace 7 días)
      hasta    — ISO date (default: ahora)
      fuente   — id_fuente filter (opcional)
      limit    — max puntos (default 500, max 2000)
    """
    permission_classes = [IsAuthenticated]
    MAX_LIMIT = 2000

    def get(self, request):
        from .models import ExchangeRateRaw

        par_str = request.query_params.get('par', 'USD/BOB')
        try:
            base, cotiz = par_str.upper().split('/')
        except ValueError:
            return Response({'error': 'par debe ser formato MONEDA/MONEDA (ej: USD/BOB)'},
                            status=status.HTTP_400_BAD_REQUEST)

        desde_str = request.query_params.get('desde')
        hasta_str = request.query_params.get('hasta')
        fuente    = request.query_params.get('fuente')
        limit     = min(int(request.query_params.get('limit', 500)), self.MAX_LIMIT)

        now = timezone.now()
        if desde_str:
            try:
                desde = timezone.datetime.fromisoformat(desde_str).replace(tzinfo=timezone.utc)
            except Exception:
                return Response({'error': 'desde: formato inválido (ISO 8601)'}, status=400)
        else:
            desde = now - timedelta(days=7)

        if hasta_str:
            try:
                hasta = timezone.datetime.fromisoformat(hasta_str).replace(tzinfo=timezone.utc)
            except Exception:
                return Response({'error': 'hasta: formato inválido (ISO 8601)'}, status=400)
        else:
            hasta = now

        cache_key = f'raw_history:{par_str}:{desde_str}:{hasta_str}:{fuente}:{limit}'
        cached = cache.get(cache_key)
        if cached:
            return Response(cached)

        qs = (
            ExchangeRateRaw.objects
            .filter(
                moneda_base      = base,
                moneda_cotizada  = cotiz,
                timestamp_captura__gte = desde,
                timestamp_captura__lte = hasta,
            )
            .order_by('timestamp_captura')
        )
        if fuente:
            qs = qs.filter(id_fuente_str=fuente)

        total = qs.count()
        puntos = qs.values(
            'timestamp_captura', 'id_fuente_str', 'precio_compra',
            'precio_venta', 'precio_promedio', 'es_valido',
        )[:limit]

        data = {
            'par':    par_str,
            'desde':  desde.isoformat(),
            'hasta':  hasta.isoformat(),
            'total':  total,
            'limit':  limit,
            'puntos': [
                {
                    'ts':      p['timestamp_captura'].isoformat(),
                    'fuente':  p['id_fuente_str'],
                    'compra':  float(p['precio_compra'])   if p['precio_compra']   else None,
                    'venta':   float(p['precio_venta'])    if p['precio_venta']    else None,
                    'mid':     float(p['precio_promedio']) if p['precio_promedio'] else None,
                    'valido':  p['es_valido'],
                }
                for p in puntos
            ],
        }
        cache.set(cache_key, data, 300)
        return Response(data)


class IntegrationSourcesView(APIView):
    """
    GET /api/v1/rates/integration-sources/
    Lista de fuentes de integración con estado de salud.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .models import ExchangeRateSource, ExchangeRateRaw
        from django.db.models import Max, Count

        sources = (
            ExchangeRateSource.objects
            .filter(id_fuente__isnull=False)
            .order_by('-priority', 'name')
        )

        # Última captura por fuente
        last_captures = {
            row['id_fuente_str']: row['last_ts']
            for row in ExchangeRateRaw.objects.values('id_fuente_str')
                       .annotate(last_ts=Max('timestamp_captura'))
        }
        # Conteo últimas 24h
        hace_24h = timezone.now() - timedelta(hours=24)
        counts_24h = {
            row['id_fuente_str']: row['cnt']
            for row in ExchangeRateRaw.objects
                       .filter(timestamp_captura__gte=hace_24h)
                       .values('id_fuente_str')
                       .annotate(cnt=Count('id'))
        }

        data = []
        for s in sources:
            last_ts = last_captures.get(s.id_fuente)
            data.append({
                'id':               s.pk,
                'id_fuente':        s.id_fuente,
                'nombre':           s.name,
                'tipo_fuente':      s.tipo_fuente,
                'url':              s.url,
                'is_active':        s.is_active,
                'priority':         s.priority,
                'necesita_revision': s.necesita_revision,
                'ultima_captura':   last_ts.isoformat() if last_ts else None,
                'capturas_24h':     counts_24h.get(s.id_fuente, 0),
                'is_healthy':       s.is_healthy,
                'consecutive_failures': s.consecutive_failures,
            })

        return Response({'fuentes': data, 'total': len(data)})


class LatestRawView(APIView):
    """
    GET /api/v1/rates/latest/
    Último dato raw por fuente para un par específico.

    Params: par (default "USD/BOB")
    """
    permission_classes = [AllowAny]

    def get(self, request):
        from .models import ExchangeRateRaw
        from django.db.models import Max

        par_str = request.query_params.get('par', 'USD/BOB')
        try:
            base, cotiz = par_str.upper().split('/')
        except ValueError:
            return Response({'error': 'par inválido'}, status=400)

        cache_key = f'integration_latest:{par_str}'
        cached = cache.get(cache_key)
        if cached:
            return Response(cached)

        # Sub-query: max timestamp por fuente en últimos 30 min
        cutoff = timezone.now() - timedelta(minutes=30)
        latest_ids = (
            ExchangeRateRaw.objects
            .filter(moneda_base=base, moneda_cotizada=cotiz,
                    timestamp_captura__gte=cutoff, es_valido=True)
            .values('id_fuente_str')
            .annotate(last_id=Max('id'))
            .values_list('last_id', flat=True)
        )

        rows = (
            ExchangeRateRaw.objects
            .filter(pk__in=latest_ids)
            .select_related('fuente')
            .order_by('-precio_compra')
        )

        por_fuente = []
        for row in rows:
            por_fuente.append({
                'fuente':     row.id_fuente_str,
                'nombre':     row.fuente.name if row.fuente else row.id_fuente_str,
                'compra':     float(row.precio_compra),
                'venta':      float(row.precio_venta) if row.precio_venta else None,
                'mid':        float(row.precio_promedio) if row.precio_promedio else None,
                'spread_pct': float(row.spread_pct) if row.spread_pct else None,
                'capturado':  row.timestamp_captura.isoformat(),
            })

        # Consenso vigente
        from .models import ExchangeRateConsensus
        consenso = ExchangeRateConsensus.objects.filter(par=par_str, vigente=True).first()

        data = {
            'par':        par_str,
            'timestamp':  timezone.now().isoformat(),
            'por_fuente': por_fuente,
            'consenso': {
                'precio':    float(consenso.precio_consenso) if consenso else None,
                'fuentes':   consenso.fuentes_count          if consenso else 0,
                'confianza': consenso.confianza_pct          if consenso else 0,
                'tendencia': consenso.tendencia              if consenso else 'NEUTRAL',
            } if consenso else None,
        }
        cache.set(cache_key, data, 60)
        return Response(data)


# ─────────────────────────────────────────────────────────────────────────────
#  Continuous Extraction Status
# ─────────────────────────────────────────────────────────────────────────────

class ExtractionStatusView(APIView):
    """
    GET /api/rates/extraction-status/

    Devuelve métricas del loop continuo de extracción de tasas:
      - Última actualización exitosa por fuente
      - Tasa de éxito en las últimas 100 iteraciones
      - Tiempo promedio de respuesta por fuente
      - Si el loop está activo (Redis lock presente)
    """
    permission_classes = [IsAuthenticated]

    @cache_response(ttl=30, key_prefix='extraction_status')
    def get(self, request):
        from django.core.cache import cache
        from django.db.models import Avg, Count, Q
        from django.utils import timezone
        from .models import RawRateSnapshot
        from .tasks import _LOOP_LOCK_KEY

        loop_active = cache.get(_LOOP_LOCK_KEY) is not None

        # Últimas 100 iteraciones por fuente
        sources = RawRateSnapshot.objects.values('source').distinct()
        stats   = []

        for row in sources:
            src = row['source']
            qs  = (RawRateSnapshot.objects
                   .filter(source=src)
                   .order_by('-fetched_at')[:100])

            total   = qs.count()
            success = qs.filter(success=True).count()
            avg_ms  = qs.aggregate(avg=Avg('response_time_ms'))['avg'] or 0
            last_ok = (RawRateSnapshot.objects
                       .filter(source=src, success=True)
                       .order_by('-fetched_at')
                       .values('fetched_at', 'currency_pair', 'raw_value')
                       .first())

            stats.append({
                'source':          src,
                'success_rate':    round(success / total * 100, 1) if total else 0,
                'total_attempts':  total,
                'avg_response_ms': round(avg_ms, 1),
                'last_success':    last_ok,
            })

        return Response({
            'loop_active':   loop_active,
            'checked_at':    timezone.now().isoformat(),
            'sources':       stats,
        })
