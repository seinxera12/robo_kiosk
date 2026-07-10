/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_SERVER_WS_URL?: string;
  readonly VITE_HEALTH_URL?: string;
  readonly VITE_KIOSK_ID?: string;
  readonly VITE_KIOSK_LOCATION?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
