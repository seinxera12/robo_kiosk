/**
 * Session logger.
 *
 * The browser cannot write files, so log records are POSTed to the launcher
 * (`POST /__log`), which appends them to `kiosk.log` next to the exe. In a
 * `npm run dev` build there is no launcher listening, so posts fail — that is
 * expected and silent (see `failed` below); DevTools is the log in dev.
 *
 * Design constraints, in priority order:
 *
 *  1. **Logging must never break the kiosk.** Every failure path here is
 *     swallowed. A logging bug that takes down an unattended kiosk is a far
 *     worse outcome than losing the log.
 *  2. **Never log audio payloads.** Binary frames are recorded by BYTE COUNT
 *     only. A single TTS reply is ~70 KB and utterances are larger; writing
 *     them out would produce a multi-megabyte log per turn and tell you nothing
 *     you could read.
 *  3. **Survive a crash.** Records are flushed on an interval and on pagehide,
 *     so a hard close still lands what happened right before it.
 */
import { appendTrace } from "../store/systemTraceStore";

export type LogLevel = "debug" | "info" | "warn" | "error";

/** Where a record came from — makes the log greppable by concern. */
export type LogChannel =
  | "app" // lifecycle: boot, config, unload
  | "ws" // socket lifecycle + every frame in/out
  | "health" // readiness polling
  | "audio" // capture/playback
  | "ui"; // user actions

export interface LogRecord {
  ts: number;
  level: LogLevel;
  channel: LogChannel;
  msg: string;
  /** Small structured payload. Never audio bytes — see module docs. */
  data?: Record<string, unknown>;
}

/** Batched POSTs; the launcher appends each record as one JSON line. */
const ENDPOINT = "/__log";
const FLUSH_INTERVAL_MS = 1000;
/** Cap the buffer so a wedged launcher cannot grow it without bound. */
const MAX_BUFFER = 500;

let buffer: LogRecord[] = [];
let timer: ReturnType<typeof setInterval> | null = null;
/**
 * Set once a post fails. In `npm run dev` there is no launcher, so the very
 * first flush 404s/refuses — after that we stop trying and stop buffering,
 * rather than retrying every second forever against a server that isn't there.
 */
let failed = false;

function post(records: LogRecord[]): void {
  const body = JSON.stringify({ records });

  // sendBeacon survives page teardown, which fetch() does not reliably do —
  // this is what makes the final records land when the window is closed.
  if (typeof navigator !== "undefined" && navigator.sendBeacon) {
    try {
      const ok = navigator.sendBeacon(
        ENDPOINT,
        new Blob([body], { type: "application/json" })
      );
      if (ok) return;
    } catch {
      /* fall through to fetch */
    }
  }

  void fetch(ENDPOINT, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body,
    keepalive: true,
  }).catch(() => {
    // No launcher (dev server) or it went away. Stop trying.
    failed = true;
  });
}

function flush(): void {
  if (buffer.length === 0) return;
  const records = buffer;
  buffer = [];
  post(records);
}

/** Record one line. Cheap and non-throwing; safe to call from hot paths. */
export function log(
  level: LogLevel,
  channel: LogChannel,
  msg: string,
  data?: Record<string, unknown>
): void {
  if (failed) return;

  buffer.push({ ts: Date.now(), level, channel, msg, data });
  if (buffer.length > MAX_BUFFER) buffer = buffer.slice(-MAX_BUFFER);

  // Errors are what you open the log to find: get them to disk immediately
  // rather than risk losing them in the buffer to whatever comes next.
  if (level === "error") {
    flush();
    return;
  }

  if (timer === null) {
    timer = setInterval(flush, FLUSH_INTERVAL_MS);
  }
}

/**
 * Start logging: install the flush timer, capture uncaught errors, and flush on
 * teardown. Called once at boot.
 */
export function startLogging(): void {
  if (typeof window === "undefined") return;

  // An uncaught exception or rejected promise is exactly the thing that will
  // otherwise vanish with the window. Route both to the log.
  window.addEventListener("error", (e) => {
    log("error", "app", "uncaught error", {
      message: String(e.message),
      source: e.filename ? `${e.filename}:${e.lineno}:${e.colno}` : undefined,
      stack: e.error instanceof Error ? e.error.stack : undefined,
    });
  });

  window.addEventListener("unhandledrejection", (e) => {
    const r = (e as PromiseRejectionEvent).reason;
    log("error", "app", "unhandled promise rejection", {
      reason: r instanceof Error ? r.message : String(r),
      stack: r instanceof Error ? r.stack : undefined,
    });
  });

  // pagehide, not unload: unload does not fire reliably on modern browsers.
  window.addEventListener("pagehide", () => {
    log("info", "app", "session ended");
    flush();
  });

  if (timer === null) timer = setInterval(flush, FLUSH_INTERVAL_MS);
}

/**
 * Mirror a line into BOTH the on-screen System Trace and the log file. Use for
 * events an operator would want in both places; use log()/appendTrace() alone
 * when a line belongs to only one.
 */
export function traceAndLog(
  glyph: "pending" | "active" | "done" | "error",
  text: string,
  channel: LogChannel = "app",
  data?: Record<string, unknown>
): void {
  appendTrace(glyph, text);
  log(glyph === "error" ? "error" : "info", channel, text, data);
}

/** Test-only. */
export const _internal = {
  flush,
  getBuffer: () => buffer,
  reset: () => {
    buffer = [];
    failed = false;
    if (timer) clearInterval(timer);
    timer = null;
  },
};
