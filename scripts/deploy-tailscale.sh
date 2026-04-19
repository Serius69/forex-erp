#!/usr/bin/env bash
# scripts/deploy-tailscale.sh — Despliegue completo Kapitalya en Tailscale
# Uso: bash scripts/deploy-tailscale.sh
set -euo pipefail

# ── Colores ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'
BOLD='\033[1m'; RESET='\033[0m'

log()  { echo -e "${GREEN}[OK]${RESET} $1"; }
info() { echo -e "${BLUE}[--]${RESET} $1"; }
warn() { echo -e "${YELLOW}[!!]${RESET} $1"; }
err()  { echo -e "${RED}[ERR]${RESET} $1" >&2; exit 1; }

COMPOSE="docker compose -f docker-compose.tailscale.yml"

# ── 1. Verificar requisitos ───────────────────────────────────────────────────
echo -e "\n${BOLD}=== Kapitalya ERP — Deploy Tailscale ===${RESET}\n"

command -v docker        >/dev/null 2>&1 || err "Docker no instalado"
command -v docker        compose >/dev/null 2>&1 || err "Docker Compose no disponible"
command -v tailscale     >/dev/null 2>&1 || warn "tailscale CLI no encontrado — instala Tailscale primero"

# ── 2. Verificar archivo .env.production ────────────────────────────────────
ENV_FILE="backend/.env.production"
[[ -f "$ENV_FILE" ]] || err "No existe $ENV_FILE — copia backend/.env.production.example y edítalo"

# Verificar que los valores placeholder fueron reemplazados
if grep -q "CAMBIAR_" "$ENV_FILE"; then
    err "Hay valores sin reemplazar en $ENV_FILE (busca CAMBIAR_*)"
fi

# ── 3. Obtener IP Tailscale ──────────────────────────────────────────────────
if command -v tailscale >/dev/null 2>&1; then
    TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "")
    if [[ -n "$TAILSCALE_IP" ]]; then
        log "Tailscale IP detectada: ${BOLD}$TAILSCALE_IP${RESET}"
        # Actualizar automáticamente en el .env si todavía tiene placeholder
        if grep -q "100.x.x.x" "$ENV_FILE"; then
            warn "Actualizando TAILSCALE_IP en $ENV_FILE con $TAILSCALE_IP"
            sed -i "s/100\.x\.x\.x/$TAILSCALE_IP/g" "$ENV_FILE"
        fi
    else
        warn "Tailscale no está conectado. Conecta con: tailscale up"
    fi
fi

# ── 4. Crear directorios necesarios ──────────────────────────────────────────
info "Creando directorios..."
mkdir -p backend/logs nginx/logs scripts/db_backup
log "Directorios listos"

# ── 5. Construir imágenes ─────────────────────────────────────────────────────
info "Construyendo imágenes Docker (esto puede tardar varios minutos)..."
$COMPOSE build --no-cache
log "Imágenes construidas"

# ── 6. Arrancar servicios de infraestructura primero ─────────────────────────
info "Iniciando postgres y redis..."
$COMPOSE up -d postgres redis
info "Esperando que postgres esté listo..."
until $COMPOSE exec -T postgres pg_isready -U kapitalya_user >/dev/null 2>&1; do
    echo -n "."
    sleep 2
done
echo ""
log "PostgreSQL listo"

# ── 7. Iniciar todos los servicios ───────────────────────────────────────────
info "Iniciando todos los servicios..."
$COMPOSE up -d
log "Servicios iniciados"

# ── 8. Esperar que backend responda ──────────────────────────────────────────
info "Esperando que el backend responda (hasta 120s)..."
TIMEOUT=120; ELAPSED=0
until curl -sf http://localhost/health/ >/dev/null 2>&1; do
    sleep 3; ELAPSED=$((ELAPSED + 3))
    [[ $ELAPSED -ge $TIMEOUT ]] && err "Backend no responde en ${TIMEOUT}s. Ver: $COMPOSE logs backend"
    echo -n "."
done
echo ""
log "Backend responde en /health/"

# ── 9. Resumen final ─────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}=== Despliegue exitoso ===${RESET}"
echo ""
TAILSCALE_IP_FINAL=$(grep "^TAILSCALE_IP=" "$ENV_FILE" | cut -d= -f2)
echo -e "  ${BOLD}Sistema:${RESET}  http://${TAILSCALE_IP_FINAL}"
echo -e "  ${BOLD}Admin:${RESET}    http://${TAILSCALE_IP_FINAL}/admin/"
echo -e "  ${BOLD}API:${RESET}      http://${TAILSCALE_IP_FINAL}/api/"
echo -e "  ${BOLD}Flower:${RESET}   http://${TAILSCALE_IP_FINAL}/flower/"
echo ""
echo -e "  ${BOLD}Logs:${RESET}     $COMPOSE logs -f"
echo -e "  ${BOLD}Estado:${RESET}   $COMPOSE ps"
echo -e "  ${BOLD}Detener:${RESET}  $COMPOSE down"
echo ""
