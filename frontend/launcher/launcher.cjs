/**
 * Voice Kiosk launcher.
 *
 * Packaged with Node's Single Executable Application (SEA) support into a
 * standalone kiosk.exe that needs no installed Node runtime. On launch it
 * serves the built frontend from memory on loopback and opens the default
 * browser at it.
 *
 * CommonJS on purpose: SEA embeds the *source text* of the entry point and runs
 * it through the CJS embedder (`embedderRunCjs`). There is no file on disk at
 * runtime, so there is no extension or nearest-package.json for Node to infer
 * ESM from — an `import` statement here fails at startup with
 * "Cannot use import statement outside a module". Keep this file CJS.
 *
 * Why serve over http://127.0.0.1 rather than opening the HTML directly — the
 * app would not work at all from file://:
 *
 *   1. getUserMedia (the microphone) requires a SECURE CONTEXT. Loopback counts
 *      as one; file:// does not. Opening the HTML directly gives a kiosk that
 *      can never hear anything.
 *   2. The app is an ES-module bundle. Browsers apply CORS rules to module
 *      scripts, and file:// origins are opaque, so the imports get blocked.
 *   3. AudioWorklet.addModule() likewise refuses to load worklets from file://,
 *      which would take out both capture and playback.
 *
 * The server started here is a static file server bound to loopback only — it
 * never accepts a connection from another machine, and it is NOT the
 * voice-server. The voice-server is remote, reached over wss:// through the
 * Tailscale Funnel, with its URL baked into the bundle at build time
 * (see frontend/.env.production).
 */
"use strict";

const { createServer } = require("node:http");
const { spawn } = require("node:child_process");
const { createWriteStream, existsSync, renameSync, statSync } = require("node:fs");
const { dirname, extname, join } = require("node:path");
const sea = require("node:sea");

/** Loopback only. Never bind 0.0.0.0 — this must not be reachable off-box. */
const HOST = "127.0.0.1";

/** First choice; we walk upward if the port is taken (see listen()). */
const BASE_PORT = 5180;
const MAX_PORT_ATTEMPTS = 20;

// --- logging ---------------------------------------------------------------
//
// The browser cannot write files, so the UI POSTs its records to /__log and we
// append them here as JSON lines. The log sits next to the exe, which is where
// someone debugging an unattended kiosk will actually look for it.
//
// process.execPath is the exe itself under SEA (not a node binary elsewhere on
// disk), so its directory is the right home for the log.

const LOG_PATH = join(dirname(process.execPath), "kiosk.log");
/** Rotate at 5 MB so an always-on kiosk cannot fill the disk. One old file. */
const LOG_MAX_BYTES = 5 * 1024 * 1024;
/** Refuse absurd payloads rather than buffer them. */
const LOG_MAX_BODY = 1 * 1024 * 1024;

function rotateIfNeeded() {
  try {
    if (existsSync(LOG_PATH) && statSync(LOG_PATH).size > LOG_MAX_BYTES) {
      renameSync(LOG_PATH, `${LOG_PATH}.1`);
    }
  } catch {
    /* rotation is best-effort; never block logging on it */
  }
}

rotateIfNeeded();

// Append mode: a restart adds to the existing log rather than destroying the
// evidence from the run that just crashed.
let logStream = createWriteStream(LOG_PATH, { flags: "a" });
logStream.on("error", (err) => {
  console.error(`[kiosk] cannot write ${LOG_PATH}: ${err.message}`);
});

function writeLogLine(obj) {
  try {
    logStream.write(JSON.stringify(obj) + "\n");
  } catch {
    /* never let logging take down the kiosk */
  }
}

/** Log our own lifecycle too, so the file explains itself without the UI. */
function logLauncher(level, msg, data) {
  writeLogLine({
    ts: Date.now(),
    level,
    channel: "launcher",
    msg,
    ...(data ? { data } : {}),
  });
}

function handleLogPost(req, res) {
  let size = 0;
  const chunks = [];

  req.on("data", (c) => {
    size += c.length;
    if (size > LOG_MAX_BODY) {
      res.writeHead(413).end();
      req.destroy();
      return;
    }
    chunks.push(c);
  });

  req.on("end", () => {
    if (res.writableEnded) return;
    try {
      const { records } = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      if (Array.isArray(records)) {
        for (const r of records) writeLogLine(r);
      }
    } catch {
      /* a malformed batch is dropped, not fatal */
    }
    // 204: the UI does not read the response and must not wait on it.
    res.writeHead(204).end();
  });
}

/**
 * Asset manifest, generated at build time (build.mjs) and embedded alongside
 * the files themselves. Maps URL path -> { key }.
 */
const manifest = JSON.parse(sea.getAsset("manifest.json", "utf8"));

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".ico": "image/x-icon",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".ttf": "font/ttf",
  ".map": "application/json; charset=utf-8",
};

function contentType(path) {
  return MIME[extname(path).toLowerCase()] || "application/octet-stream";
}

const server = createServer((req, res) => {
  // Only ever serve embedded assets. Nothing is read from disk, so there is no
  // path-traversal surface here.
  let path = (req.url || "/").split("?")[0].split("#")[0];

  // Log ingest from the UI. Checked before the SPA fallback below, which would
  // otherwise happily answer this with index.html.
  if (path === "/__log") {
    if (req.method !== "POST") {
      res.writeHead(405).end();
      return;
    }
    handleLogPost(req, res);
    return;
  }

  if (path === "/") path = "/index.html";

  const entry = manifest[path];

  // Single-page app: unknown paths fall back to index.html so a refresh on a
  // client-side route still boots the app.
  const key = entry ? entry.key : manifest["/index.html"].key;
  const type = entry ? contentType(path) : "text/html; charset=utf-8";

  const body = Buffer.from(sea.getAsset(key));
  res.writeHead(200, {
    "content-type": type,
    "content-length": body.length,
    // The bundle is baked into this exe: never let a stale cached asset from a
    // previous build outlive an upgrade.
    "cache-control": "no-store",
  });
  res.end(body);
});

/** Open the user's default browser, per-platform. */
function openBrowser(url) {
  let cmd;
  let args;
  if (process.platform === "win32") {
    // `start` is a cmd builtin, not an exe. The empty "" is the window-title
    // argument — without it, cmd treats a quoted URL as the title and silently
    // opens nothing.
    cmd = "cmd";
    args = ["/c", "start", "", url];
  } else if (process.platform === "darwin") {
    cmd = "open";
    args = [url];
  } else {
    cmd = "xdg-open";
    args = [url];
  }

  const child = spawn(cmd, args, { stdio: "ignore", detached: true });
  child.on("error", () => {
    console.log(`Could not open a browser automatically. Open this URL:\n  ${url}`);
  });
  child.unref();
}

/**
 * Bind the first free port at or above BASE_PORT. A kiosk machine may already
 * have something on 5180 (including a second copy of this launcher), and dying
 * with EADDRINUSE would just look like "the exe doesn't work".
 */
function listen(port, attempt) {
  attempt = attempt || 0;

  server.once("error", (err) => {
    if (err.code === "EADDRINUSE" && attempt < MAX_PORT_ATTEMPTS) {
      listen(port + 1, attempt + 1);
      return;
    }
    console.error(`Failed to start the local server: ${err.message}`);
    process.exit(1);
  });

  server.listen(port, HOST, () => {
    const url = `http://${HOST}:${port}/`;
    console.log("Voice Kiosk");
    console.log(`  serving on ${url}`);
    console.log(`  log file:   ${LOG_PATH}`);
    console.log("  opening your browser...");
    console.log("\nClose this window to shut down the kiosk.");
    logLauncher("info", "launcher started", { url, pid: process.pid });
    if (!process.env.KIOSK_NO_BROWSER) openBrowser(url);
  });
}

// Record why we went away, so an unattended kiosk that vanished overnight
// leaves behind the reason.
process.on("uncaughtException", (err) => {
  logLauncher("error", "launcher crashed", {
    message: err.message,
    stack: err.stack,
  });
  logStream.end();
  process.exit(1);
});

for (const sig of ["SIGINT", "SIGTERM"]) {
  process.on(sig, () => {
    logLauncher("info", "launcher stopped", { signal: sig });
    logStream.end(() => process.exit(0));
  });
}

listen(BASE_PORT);
