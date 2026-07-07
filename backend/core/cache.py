"""Central registry of cache keys and TTLs for the Kapitalya ERP."""

# ── TTLs (seconds) ────────────────────────────────────────────────────────────
TTL_PARALLEL_RATE     = 60
TTL_SPREAD            = 30
TTL_CAPITAL_POSITION  = 30
TTL_KPI               = 300
TTL_EXCHANGE_RATE     = 120
TTL_FORECAST          = 3600

# ── Key templates ─────────────────────────────────────────────────────────────
KEY_PARALLEL_RATE     = 'parallel_rate:{currency}'
KEY_SPREAD            = 'spread:{currency_from}:{currency_to}'
KEY_CAPITAL_POSITION  = 'capital_position:{branch_id}'
KEY_KPI               = 'kpi:{branch_id}:{date}'
KEY_EXCHANGE_RATE     = 'rate_{currency_from}_{currency_to}'
KEY_PRIMARY_RATE      = 'primary_rate_{currency_from}_{currency_to}'
KEY_FORECAST          = 'forecast:{currency}:{horizon}'
