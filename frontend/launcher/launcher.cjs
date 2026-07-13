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
const { extname } = require("node:path");
const sea = require("node:sea");

/** Loopback only. Never bind 0.0.0.0 — this must not be reachable off-box. */
const HOST = "127.0.0.1";

/** First choice; we walk upward if the port is taken (see listen()). */
const BASE_PORT = 5180;
const MAX_PORT_ATTEMPTS = 20;

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
    console.log("  opening your browser...");
    console.log("\nClose this window to shut down the kiosk.");
    if (!process.env.KIOSK_NO_BROWSER) openBrowser(url);
  });
}

listen(BASE_PORT);
