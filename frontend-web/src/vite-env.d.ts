/// <reference types="vite/client" />

// Tipado explícito de las variables de entorno VITE_* del proyecto.
// Vite expone estas variables a través de import.meta.env con el prefijo VITE_.
interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string;
  readonly VITE_WS_BASE_URL: string;
  readonly VITE_APP_NAME?: string;
  readonly VITE_APP_VERSION?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
