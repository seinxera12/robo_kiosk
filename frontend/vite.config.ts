import { resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// See FRONTEND_MIGRATION_PLAN.md FE-1. Env vars are VITE_* (§3 config table).
export default defineConfig({
  plugins: [react()],

  build: {
    rollupOptions: {
      // The two AudioWorklets are built as their own entry points so they are
      // emitted as real, TRANSPILED .js assets that addModule() can load.
      //
      // They must NOT be reached via `new URL("./x-worklet.ts", import.meta.url)`.
      // Vite resolves that as a static asset and keys the MIME type off the file
      // extension -- and ".ts" is MPEG Transport Stream, not TypeScript. The
      // result is the raw, untranspiled TS source inlined as a
      // `data:video/mp2t;base64,...` URL, which every browser rejects with
      // "Unable to load a worklet's module." It works under `vite dev` only
      // because the dev server transpiles .ts on request, so the bug is
      // invisible until you ship a production build.
      //
      // Worklets run in a separate global scope with no imports, so a plain
      // entry (not a chunk) is exactly right here.
      input: {
        index: resolve(__dirname, "index.html"),
        "playback-worklet": resolve(__dirname, "src/audio/playback-worklet.ts"),
        "capture-worklet": resolve(__dirname, "src/audio/capture-worklet.ts"),
      },
      output: {
        // Stable, unhashed names for the worklets so the loaders can reference
        // them by a fixed path; everything else keeps content hashing.
        entryFileNames: (chunk) =>
          chunk.name.endsWith("-worklet")
            ? "assets/[name].js"
            : "assets/[name]-[hash].js",
      },
    },
  },

  server: {
    host: true,
    port: 5173,
  },
  test: {
    globals: true,
    environment: "node",
  },
});
