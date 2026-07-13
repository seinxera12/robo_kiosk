/**
 * Runtime configuration (FE-1, plan §3).
 *
 * Deployment shape: the voice-server is reached ONLY through a Tailscale Funnel
 * (public HTTPS/TLS). The funnel fronts the whole server on a SINGLE origin —
 * `/ws` and `/health` share one host and one port, and the scheme is always
 * TLS (`wss://` / `https://`). There is no plain-HTTP or raw-IP access, and the
 * old two-port split (8765 for WS, 8000 for health) does not exist there.
 *
 * VITE_SERVER_WS_URL / VITE_HEALTH_URL therefore carry the funnel origin and
 * are baked in at build time (see .env.production). They are the authoritative
 * source in any packaged build.
 *
 * The window.location fallback below only serves the case where the app is
 * served BY the voice-server itself (same origin, dev/self-hosted). It is NOT
 * a sane default for the packaged launcher, which serves the UI from
 * http://127.0.0.1:<port> — deriving from that location would point the socket
 * at the launcher rather than the funnel. Hence: env wins, always.
 */

/** Same-origin fallback ports (dev / self-hosted only — not the funnel). */
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

/**
 * True when the resolved WS URL points at the loopback interface. In a packaged
 * build that means the funnel URL was never baked in and the location fallback
 * kicked in — the socket would dial the launcher's own static file server
 * instead of the voice-server. Silent otherwise: the socket just never connects.
 */
function isLoopback(url: string): boolean {
  return /^wss?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:|\/)/i.test(url);
}

const serverWsUrl = env("VITE_SERVER_WS_URL", defaultWsUrl());
const healthUrl = env("VITE_HEALTH_URL", defaultHealthUrl());

if (import.meta.env?.PROD && isLoopback(serverWsUrl)) {
  console.error(
    "[config] Production build resolved a loopback WebSocket URL " +
      `(${serverWsUrl}). VITE_SERVER_WS_URL was not baked in at build time — ` +
      "the app will not reach the voice-server. Check frontend/.env.production."
  );
}

export const config: AppConfig = Object.freeze({
  serverWsUrl,
  healthUrl,
  kioskId: env("VITE_KIOSK_ID", "kiosk-01"),
  kioskLocation: env("VITE_KIOSK_LOCATION", "Floor 1 Lobby"),
});

// Exported for unit testing the derivation logic in isolation.
export const _internal = {
  defaultWsUrl,
  defaultHealthUrl,
  isSecurePage,
  currentHost,
  isLoopback,
};
