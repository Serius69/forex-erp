from rest_framework.pagination import CursorPagination, PageNumberPagination


class TransactionCursorPagination(CursorPagination):
    """Cursor pagination para Transaction — evita COUNT(*) costoso en tablas grandes."""
    page_size             = 25
    page_size_query_param = 'page_size'
    max_page_size         = 200
    ordering              = '-created_at'


class RawRateCursorPagination(CursorPagination):
    """Cursor pagination para ExchangeRateRaw — datasets de millones de filas."""
    page_size             = 50
    page_size_query_param = 'page_size'
    max_page_size         = 500
    ordering              = '-timestamp_captura'


class StandardPagePagination(PageNumberPagination):
    page_size             = 25
    page_size_query_param = 'page_size'
    max_page_size         = 200


# Alias para la referencia en settings.py
KapitalyaCursorPagination = TransactionCursorPagination
