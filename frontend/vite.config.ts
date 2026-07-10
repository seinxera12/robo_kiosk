import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// See FRONTEND_MIGRATION_PLAN.md FE-1. Env vars are VITE_* (§3 config table).
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
  },
  test: {
    globals: true,
    environment: "node",
  },
});
