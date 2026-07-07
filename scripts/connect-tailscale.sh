#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════════════
# connect-tailscale.sh — Conectar un nuevo dispositivo a Kapitalya ERP
#
# Ejecutar en CADA dispositivo cliente que necesite acceder al sistema.
# El servidor principal ya debe estar desplegado con deploy-tailscale.sh.
#
# Uso: bash scripts/connect-tailscale.sh
# ════════════════════════════════════════════════════════════════════════════
set -euo pipefail

BOLD='\033[1m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'
YELLOW='\033[1;33m'; NC='\033[0m'

echo -e "\n${BOLD}══════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}  Kapitalya ERP — Conectar dispositivo a Tailscale${NC}"
echo -e "${BOLD}══════════════════════════════════════════════════════════${NC}\n"

echo -e "${CYAN}PASO 1: Instalar Tailscale${NC}"
echo "  Linux (Ubuntu/Debian):"
echo "    curl -fsSL https://tailscale.com/install.sh | sh"
echo ""
echo "  Windows:"
echo "    Descargar de: https://tailscale.com/download/windows"
echo "    Instalar y seguir el asistente de configuración"
echo ""
echo "  macOS:"
echo "    brew install tailscale"
echo "    O desde: https://tailscale.com/download/macos"
echo ""
echo "  Android / iOS:"
echo "    Buscar 'Tailscale' en Google Play / App Store"
echo ""

echo -e "${CYAN}PASO 2: Iniciar sesión en Tailscale${NC}"
echo "  Linux/macOS (terminal):"
echo "    sudo tailscale up"
echo "  (Se abrirá un navegador para autenticarte con la misma cuenta)"
echo ""

echo -e "${CYAN}PASO 3: Verificar conexión${NC}"
echo "  tailscale status"
echo "  (Deberías ver el servidor Kapitalya en la lista)"
echo ""

echo -e "${CYAN}PASO 4: Obtener IP del servidor Kapitalya${NC}"
echo "  En el SERVIDOR, ejecutar: tailscale ip -4"
echo "  Ejemplo de IP: 100.64.0.1"
echo ""

echo -e "${CYAN}PASO 5: Acceder al sistema${NC}"
echo "  Abrir navegador y navegar a:"
echo "    http://100.X.X.X       ← reemplaza con la IP del servidor"
echo "    http://nombre-servidor.tail-XXXXX.ts.net  ← si MagicDNS está activo"
echo ""

if command -v tailscale >/dev/null 2>&1; then
    MY_IP=$(tailscale ip -4 2>/dev/null || echo "no conectado")
    PEERS=$(tailscale status 2>/dev/null | grep -v "^#" | head -10 || echo "")
    echo -e "${GREEN}══ Estado actual de este dispositivo ══${NC}"
    echo "  Mi IP Tailscale: $MY_IP"
    if [[ -n "$PEERS" ]]; then
        echo "  Dispositivos en la red:"
        echo "$PEERS" | while IFS= read -r line; do echo "    $line"; done
    fi
    echo ""
fi

echo -e "${YELLOW}NOTAS IMPORTANTES:${NC}"
echo "  • Todos los dispositivos deben usar la misma cuenta de Tailscale"
echo "  • El tráfico está cifrado con WireGuard (no se necesita VPN adicional)"
echo "  • Las IPs 100.x.x.x son privadas y no accesibles desde internet"
echo "  • Si usas MagicDNS, el hostname funciona sin recordar la IP"
echo ""
