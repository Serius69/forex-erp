#!/usr/bin/env bash
# Preflight de producción: verifica que el .env no tenga placeholders antes de
# levantar docker-compose.prod.yml. (La ruta tailscale ya lo valida en
# scripts/deploy-tailscale.sh; esta cubre `docker compose -f docker-compose.prod.yml up`.)
#
# Uso: ./scripts/preflight_prod.sh [ruta-al-env]   (default: backend/.env.production)
set -euo pipefail

ENV_FILE="${1:-backend/.env.production}"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "ERROR: no existe $ENV_FILE — copia backend/.env.production.example y configura secretos reales." >&2
    exit 1
fi

if grep -q "CAMBIAR_" "$ENV_FILE"; then
    echo "ERROR: $ENV_FILE contiene placeholders CAMBIAR_*:" >&2
    grep -n "CAMBIAR_" "$ENV_FILE" | sed 's/=.*/=***/' >&2
    echo "Configura secretos reales antes de levantar producción." >&2
    exit 1
fi

for var in SECRET_KEY DB_PASSWORD; do
    if ! grep -qE "^${var}=." "$ENV_FILE"; then
        echo "ERROR: falta ${var} en $ENV_FILE." >&2
        exit 1
    fi
done

echo "OK: $ENV_FILE sin placeholders y con variables críticas presentes."
