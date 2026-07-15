"""
Expiración de tasas activas duplicadas.

Invariante del modelo `ExchangeRate`: `valid_until IS NULL` ⇒ tasa VIGENTE.
Debe existir **una sola** tasa vigente por
`(currency_from, currency_to, market_type, rate_source)`: la de mayor `valid_from`.

Los caminos runtime (fx_engine, aggregator, fetchers, services) ya cierran la
anterior antes de insertar la nueva. Pero los loaders históricos
(`load_competition_rates`, `derive_empresa_rates`, importadores de Sheets)
insertan una fila por fecha dejando `valid_until` en NULL, por lo que TODA la
serie queda "vigente" y consultas como `filter(valid_until__isnull=True)` o
`calcular_spreads` degeneran a O(N).

`expire_stale_active_rates()` normaliza eso: por cada grupo deja activa solo la
fila más reciente y cierra las demás con `valid_until = valid_from` de la fila
siguiente (intervalos contiguos → las consultas `valid_until__gte=fecha` siguen
resolviendo la tasa vigente en cualquier instante histórico). Es idempotente.
"""
from django.db import connection, transaction

from .models import ExchangeRate


def expire_stale_active_rates(market_type=None, currency_from_id=None,
                              currency_to_id=None):
    """
    Cierra las tasas vigentes redundantes dejando una sola por grupo.

    Filtros opcionales acotan el barrido (útil desde un loader que solo tocó su
    propio mercado). Sin filtros normaliza toda la tabla.

    Devuelve el número de filas cerradas.
    """
    table = ExchangeRate._meta.db_table
    where = ["valid_until IS NULL"]
    params = []
    if market_type is not None:
        where.append("market_type = %s")
        params.append(market_type)
    if currency_from_id is not None:
        where.append("currency_from_id = %s")
        params.append(currency_from_id)
    if currency_to_id is not None:
        where.append("currency_to_id = %s")
        params.append(currency_to_id)
    where_sql = " AND ".join(where)

    # LEAD(valid_from): para la fila más reciente de cada grupo devuelve NULL
    # (queda vigente); para el resto, el valid_from de la siguiente → intervalo
    # contiguo. NULLs de rate_source_id se agrupan juntos (semántica de PARTITION BY).
    sql = f"""
        WITH ranked AS (
            SELECT id,
                   LEAD(valid_from) OVER (
                       PARTITION BY currency_from_id, currency_to_id,
                                    market_type, rate_source_id
                       ORDER BY valid_from, id
                   ) AS next_from
            FROM {table}
            WHERE {where_sql}
        )
        UPDATE {table} AS e
        SET valid_until = ranked.next_from,
            is_primary  = FALSE,
            updated_at  = NOW()
        FROM ranked
        WHERE e.id = ranked.id
          AND ranked.next_from IS NOT NULL;
    """
    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute(sql, params)
            return cur.rowcount
