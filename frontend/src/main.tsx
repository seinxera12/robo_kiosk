import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { ConsoleRoot } from "./components/console/ConsoleRoot";
import { config } from "./config";
import { log, startLogging } from "./services/logger";
import "./styles.css";
import "./styles/tokens.css";
import "./styles/console.css";

// Before anything else, so a crash during boot is still captured.
startLogging();

// The endpoints actually in use. First thing to check when the kiosk cannot
// reach the server — the exe bakes these in at build time, so the log is the
// only way to see which server a given exe was built against.
log("info", "app", "kiosk starting", {
  serverWsUrl: config.serverWsUrl,
  healthUrl: config.healthUrl,
  kioskId: config.kioskId,
  kioskLocation: config.kioskLocation,
  userAgent: navigator.userAgent,
});

const rootEl = document.getElementById("root");
if (!rootEl) {
  throw new Error("Root element #root not found");
}

// Neo-HUD console (spec migration) is now the default UI. The old chat UI
// (<App/>) is kept as a fallback/reference — deprecated, not deleted, until
// the preserve-functionality checklist has been manually verified against a
// real backend (see .devnotes/ui-changes). Pass ?legacy=1 to render it.
const useLegacy = new URLSearchParams(location.search).has("legacy");

createRoot(rootEl).render(
  <React.StrictMode>
    {useLegacy ? <App /> : <ConsoleRoot />}
  </React.StrictMode>
);
