/**
 * Runtime configuration (FE-1, plan §3).
 *
 * Values come from VITE_* env vars, falling back to defaults derived from
 * window.location. Edge cases handled per plan:
 *  - missing env  -> localhost / location-derived defaults
 *  - https page   -> derive wss:// (secure WebSocket) for the WS URL
 */

const DEFAULT_WS_PORT = 8765;
const DEFAULT_HEALTH_PORT = 8000;

function currentHost(): string {
  if (typeof window !== "undefined" && window.location?.hostname) {
    return window.location.hostname;
  }
  return "localhost";
}

/** True when the page is served over https (so WS must be wss). */
function isSecurePage(): boolean {
  return typeof window !== "undefined" && window.location?.protocol === "https:";
}

function defaultWsUrl(): string {
  const scheme = isSecurePage() ? "wss" : "ws";
  return `${scheme}://${currentHost()}:${DEFAULT_WS_PORT}/ws`;
}

function defaultHealthUrl(): string {
  const scheme = isSecurePage() ? "https" : "http";
  return `${scheme}://${currentHost()}:${DEFAULT_HEALTH_PORT}/health`;
}

/** Read a VITE_ env var, returning `fallback` when unset/empty. */
function env(name: string, fallback: string): string {
  const raw = (import.meta.env?.[name] as string | undefined)?.trim();
  return raw && raw.length > 0 ? raw : fallback;
}

export interface AppConfig {
  /** WebSocket endpoint, e.g. ws://host:8765/ws (plan §3, REF §9.2). */
  readonly serverWsUrl: string;
  /** Health endpoint, e.g. http://host:8000/health (REF §4.1). */
  readonly healthUrl: string;
  /** Sent in session_start (REF §3.3.1). */
  readonly kioskId: string;
  /** Sent in session_start; feeds the system prompt's Kiosk Location. */
  readonly kioskLocation: string;
}

export const config: AppConfig = Object.freeze({
  serverWsUrl: env("VITE_SERVER_WS_URL", defaultWsUrl()),
  healthUrl: env("VITE_HEALTH_URL", defaultHealthUrl()),
  kioskId: env("VITE_KIOSK_ID", "kiosk-01"),
  kioskLocation: env("VITE_KIOSK_LOCATION", "Floor 1 Lobby"),
});

// Exported for unit testing the derivation logic in isolation.
export const _internal = {
  defaultWsUrl,
  defaultHealthUrl,
  isSecurePage,
  currentHost,
};
