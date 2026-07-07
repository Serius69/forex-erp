// src/config.ts — Configuración central de la app móvil Forex ERP
//
// URL base de la API del backend Django (Forex ERP).
//
// El backend Django escucha en el puerto 8007 dentro del contenedor.
// Según cómo levantes el backend, la URL accesible desde el dispositivo cambia:
//
//   • docker compose up        → nginx publica en el host 9091:80 (API vía /api)
//                                y 9092:8007 (backend directo).
//                                Emulador Android:  http://10.0.2.2:9092/api
//   • runserver 0.0.0.0:8007   → backend directo en el host, puerto 8007.
//                                Emulador Android:  http://10.0.2.2:8007/api
//   • Dispositivo físico       → usar la IP LAN del servidor.
//                                Ej: http://192.168.1.50:8007/api
//
// `10.0.2.2` es el alias que el emulador Android usa para el `localhost` del host.
// El servidor de desarrollo de Metro corre en el puerto 8081 (por defecto de RN).

const HOST_ANDROID_EMULATOR = '10.0.2.2';

// Puerto del backend tal como queda expuesto en el host.
// Cambiar a 9092 si levantas todo con `docker compose up` (mapeo 9092:8007).
const API_PORT = 8007;

export const API_BASE_URL = `http://${HOST_ANDROID_EMULATOR}:${API_PORT}/api`;

// Puerto del bundler Metro (informativo; se fija con `react-native start --port`).
export const METRO_PORT = 8081;

// Timeout de las peticiones HTTP (ms). Al vencerse se aborta el fetch y se lanza
// un error de red ('Network request timed out') que offlineQueue.isNetworkError
// reconoce como fallo de conectividad (reintentable).
export const REQUEST_TIMEOUT_MS = 15000;
