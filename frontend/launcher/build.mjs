/**
 * Packages the built frontend + launcher into a standalone Windows kiosk.exe.
 *
 * Pipeline:
 *   1. read dist/            (caller must have run `vite build` first)
 *   2. write a SEA config whose `assets` map embeds every dist file
 *   3. node --experimental-sea-config  -> sea-prep.blob
 *   4. copy the node binary -> kiosk.exe
 *   5. postject the blob into kiosk.exe
 *
 * The resulting exe carries the whole UI inside it and needs no installed Node.
 *
 * NOTE: the exe is built from the *running* node binary, so it targets the host
 * platform. Build on Windows to ship a Windows exe — SEA has no cross-compile.
 */
import { execFileSync } from "node:child_process";
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const here = fileURLToPath(new URL(".", import.meta.url));
const frontendDir = resolve(here, "..");
const distDir = join(frontendDir, "dist");
const outDir = join(frontendDir, "release");
const workDir = join(outDir, ".work");

const isWindows = process.platform === "win32";
const exeName = isWindows ? "kiosk.exe" : "kiosk";

/** Node's SEA fuse sentinel. Fixed constant — do not invent a value. */
const FUSE = "NODE_SEA_FUSE_fce680ab2cc467b6e072b8b5df1996b2";

function fail(msg) {
  console.error(`\n[build] ${msg}\n`);
  process.exit(1);
}

// --- 1. collect dist -------------------------------------------------------

let distStat;
try {
  distStat = statSync(distDir);
} catch {
  fail("dist/ not found. Run `npm run build` before packaging.");
}
if (!distStat.isDirectory()) fail("dist/ is not a directory.");

/** Recursively list every file under dist/. */
function walk(dir) {
  const out = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) out.push(...walk(full));
    else out.push(full);
  }
  return out;
}

const files = walk(distDir);
if (files.length === 0) fail("dist/ is empty. Run `npm run build` first.");

// Guard: refuse to ship a bundle that never got the funnel URL baked in. A
// loopback WS URL here means .env.production was missed and the exe would come
// out pointing at its own static file server -- which fails silently at runtime
// as a socket that simply never connects.
const jsBundles = files.filter((f) => f.endsWith(".js"));
const bundleText = jsBundles.map((f) => readFileSync(f, "utf8")).join("");
const wsUrls = [...bundleText.matchAll(/wss?:\/\/[^"'`\s]+\/ws/g)].map((m) => m[0]);
if (wsUrls.length === 0) {
  fail(
    "No WebSocket URL found in the built bundle. Expected VITE_SERVER_WS_URL to " +
      "be inlined by `vite build` (see .env.production)."
  );
}
if (wsUrls.some((u) => /\/\/(localhost|127\.0\.0\.1|\[::1\])[:/]/i.test(u))) {
  fail(
    `Refusing to package: the bundle points at a loopback voice-server (${wsUrls.join(", ")}).\n` +
      "The exe would not reach the remote server. Check frontend/.env.production."
  );
}
console.log(`[build] bundle targets: ${[...new Set(wsUrls)].join(", ")}`);

// --- 2. SEA config with embedded assets ------------------------------------

rmSync(outDir, { recursive: true, force: true });
mkdirSync(workDir, { recursive: true });

/** URL path ("/assets/index-x.js") -> asset key. Keys must be unique strings. */
const assets = {};
const manifest = {};

for (const file of files) {
  const urlPath = "/" + relative(distDir, file).split(sep).join("/");
  const key = urlPath; // key by URL path: unique by construction
  assets[key] = file;
  manifest[urlPath] = { key };
}

const manifestPath = join(workDir, "manifest.json");
writeFileSync(manifestPath, JSON.stringify(manifest));
assets["manifest.json"] = manifestPath;

const seaConfig = {
  // CommonJS entry point, not ESM: SEA embeds the source text and runs it via
  // the CJS embedder, so an `import` statement here dies at startup with
  // "Cannot use import statement outside a module". See launcher.cjs.
  main: join(here, "launcher.cjs"),
  output: join(workDir, "sea-prep.blob"),
  disableExperimentalSEAWarning: true,
  // Embed dist/ into the executable.
  assets,
};

const seaConfigPath = join(workDir, "sea-config.json");
writeFileSync(seaConfigPath, JSON.stringify(seaConfig, null, 2));

console.log(`[build] embedding ${files.length} asset(s) from dist/`);

// --- 3. blob ---------------------------------------------------------------

execFileSync(process.execPath, ["--experimental-sea-config", seaConfigPath], {
  stdio: "inherit",
});

// --- 4. copy the node binary ------------------------------------------------

const exePath = join(outDir, exeName);
copyFileSync(process.execPath, exePath);

// --- 5. inject --------------------------------------------------------------

/**
 * Locate postject's CLI. Preferred: the copy in node_modules. But this repo's
 * node_modules is often installed from WSL, whose .bin symlinks Windows npm
 * cannot read — so `npm install` on the Windows side may not have populated it.
 * Fall back to `npx`, which fetches it on demand.
 */
function postjectArgs() {
  const local = join(frontendDir, "node_modules", "postject", "dist", "cli.js");
  const args = [exePath, "NODE_SEA_BLOB", seaConfig.output, "--sentinel-fuse", FUSE];
  if (existsSync(local)) return { cmd: process.execPath, args: [local, ...args] };
  const npx = isWindows ? "npx.cmd" : "npx";
  return { cmd: npx, args: ["--yes", "postject", ...args] };
}

// postject rewrites the binary in place, which invalidates the Node binary's
// Authenticode signature. That is expected and harmless for an unsigned
// internal tool; it prints "signature seems corrupted" and continues.
const { cmd, args } = postjectArgs();
execFileSync(cmd, args, { stdio: "inherit", shell: isWindows });

rmSync(workDir, { recursive: true, force: true });

const sizeMb = (statSync(exePath).size / 1024 / 1024).toFixed(1);
console.log(`\n[build] ${relative(frontendDir, exePath)}  (${sizeMb} MB)`);
console.log("[build] done — run it to launch the kiosk.");
