import { config } from "./config";
import { useSession } from "./useSession";
import { useStore } from "./store/useStore";
import { Transcript } from "./components/Transcript";
import { TextInput } from "./components/TextInput";
import { StatusBar } from "./components/StatusBar";
import { MicButton } from "./components/MicButton";
import { HealthPanel } from "./components/HealthPanel";

/**
 * @deprecated Superseded by the Neo-HUD console (components/console/ConsoleRoot).
 * Kept as a fallback/reference — render with `?legacy=1` — until the
 * preserve-functionality checklist (.devnotes/ui-changes) is manually
 * verified against a real backend. Do not build new features on this path.
 */
export function App() {
  const session = useSession();
  const softError = useStore((s) => s.softError);

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>Voice Kiosk</h1>
        <span className="kiosk-tag">
          {config.kioskId} · {config.kioskLocation}
        </span>
      </header>

      <StatusBar controller={session?.controller ?? null} />

      {softError && (
        <div className="soft-error" role="alert">
          {softError}
        </div>
      )}

      <main className="app-main">
        <Transcript />
      </main>

      <footer className="app-footer">
        {session && <MicButton voice={session.voice} />}
        {session && <TextInput controller={session.controller} />}
      </footer>

      <HealthPanel />
    </div>
  );
}
