/**
 * Resolves the AudioWorklet module URLs.
 *
 * Do NOT go back to `new URL("./playback-worklet.ts", import.meta.url)`.
 * Vite treats that as a static asset reference and derives the MIME type from
 * the file extension — and `.ts` is MPEG Transport Stream, not TypeScript. The
 * production build therefore inlines the raw, UNTRANSPILED TypeScript source as
 * a `data:video/mp2t;base64,...` URL. `addModule()` rejects it ("Unable to load
 * a worklet's module"), killing playback and mic capture together. `vite dev`
 * hides this because the dev server transpiles `.ts` on request.
 *
 * Instead the worklets are separate Rollup entries (see vite.config.ts), emitted
 * as real transpiled JS at a stable, unhashed path.
 *
 * Dev serves the TypeScript source directly (the dev server transpiles it);
 * production points at the built asset.
 */

/** Vite rewrites BASE_URL to the deployment base; "/" for the kiosk launcher. */
const base = import.meta.env.BASE_URL || "/";

/**
 * Dev serves the TypeScript source straight from `src/` (the dev server
 * transpiles it on request); production loads the built entry from `assets/`.
 *
 * The dev path is a plain string, deliberately NOT `new URL(..., import.meta.url)`:
 * that form makes Vite emit the .ts file as a build asset even inside a
 * `import.meta.env.DEV` branch that can never run in production.
 */
export const PLAYBACK_WORKLET_URL = import.meta.env.DEV
  ? "/src/audio/playback-worklet.ts"
  : `${base}assets/playback-worklet.js`;

export const CAPTURE_WORKLET_URL = import.meta.env.DEV
  ? "/src/audio/capture-worklet.ts"
  : `${base}assets/capture-worklet.js`;
