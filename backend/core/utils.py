from datetime import date, timedelta
from django.utils.dateparse import parse_date


def parse_date_range(request, default_days: int = 30):
    """
    Parses date_from / date_to from request query params.
    Falls back gracefully on missing or malformed values.
    Returns (date_from, date_to) as date objects.
    """
    date_to   = parse_date(request.query_params.get('date_to',   '')) or date.today()
    date_from = parse_date(request.query_params.get('date_from', '')) or (
        date_to - timedelta(days=default_days)
    )
    return date_from, date_to
