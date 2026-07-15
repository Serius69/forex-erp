"""API de indicadores macro — lectura para el dashboard y análisis."""
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import MacroIndicator
from .serializers import MacroIndicatorSerializer


class MacroIndicatorViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/macro/indicators/                 — lista paginada (filtro ?series=)
    GET /api/macro/indicators/summary/         — último punto de cada serie
    GET /api/macro/indicators/series/?series=X — serie completa ordenada por fecha
    """
    serializer_class   = MacroIndicatorSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = MacroIndicator.objects.all()
        series = self.request.query_params.get('series')
        if series:
            qs = qs.filter(series=series)
        return qs

    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Último punto de cada serie + antigüedad, para el panel macro."""
        today = timezone.localdate()
        out = []
        for series, label in MacroIndicator.SERIES_CHOICES:
            row = MacroIndicator.latest(series)
            if row is None:
                continue
            out.append({
                'series':       series,
                'series_label': label,
                'date':         row.date,
                'value':        row.value,
                'unit':         row.unit,
                'source':       row.source,
                'age_days':     (today - row.date).days,
            })
        return Response({'indicators': out, 'as_of': today})

    @action(detail=False, methods=['get'])
    def series(self, request):
        """Serie completa (ascendente) para graficar. Requiere ?series=."""
        series = request.query_params.get('series')
        valid = {s for s, _ in MacroIndicator.SERIES_CHOICES}
        if series not in valid:
            return Response(
                {'error': f'series inválida; opciones: {sorted(valid)}'}, status=400)
        rows = (MacroIndicator.objects.filter(series=series)
                .order_by('date')
                .values('date', 'value', 'unit', 'source'))
        return Response({'series': series, 'points': list(rows)})


class NewsViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/macro/news/            — noticias recientes con sentimiento
    GET /api/macro/news/pulse/      — índice de sentimiento + titulares clave
    """
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        from rest_framework import serializers

        from .models import NewsItem

        class NewsSerializer(serializers.ModelSerializer):
            class Meta:
                model = NewsItem
                fields = ['title', 'url', 'source', 'published_at',
                          'sentiment', 'keywords']
        return NewsSerializer

    def get_queryset(self):
        from .models import NewsItem
        qs = NewsItem.objects.all()
        if self.request.query_params.get('signal') == 'true':
            qs = qs.exclude(sentiment=0)
        return qs

    @action(detail=False, methods=['get'])
    def pulse(self, request):
        """Índice de sentimiento actual + los titulares que más pesan."""
        from datetime import timedelta

        from .models import MacroIndicator, NewsItem

        idx = MacroIndicator.latest('sentimiento_dolar')
        cutoff = timezone.now() - timedelta(hours=48)
        top = (NewsItem.objects.filter(published_at__gte=cutoff)
               .exclude(sentiment=0))
        alcistas = list(top.order_by('-sentiment')[:5].values(
            'title', 'url', 'source', 'sentiment', 'published_at'))
        bajistas = list(top.order_by('sentiment')[:5].values(
            'title', 'url', 'source', 'sentiment', 'published_at'))
        return Response({
            'index': float(idx.value) if idx else None,
            'index_date': idx.date if idx else None,
            'label': ('alcista' if idx and idx.value > 0.15 else
                      'bajista' if idx and idx.value < -0.15 else 'neutral'),
            'noticias_48h': top.count(),
            'alcistas': alcistas,
            'bajistas': [b for b in bajistas if b['sentiment'] < 0],
        })
