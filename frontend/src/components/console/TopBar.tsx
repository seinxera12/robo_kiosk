import { useEffect, useState } from "react";
import { useStore } from "../../store/useStore";
import type { ConnectionState } from "../../store/types";

/**
 * Top bar (spec §3.1). Connection pill mirrors the real WebSocket lifecycle
 * (REF/store ConnectionState) — there are 5 real states, not the spec's 4, so
 * `connected` (socket open, awaiting session_ack) is folded into CONNECTING
 * rather than invented as a distinct pill.
 */

type PillState = "LIVE" | "CONNECTING" | "RECONNECTING" | "OFFLINE";

const PILL_MAP: Record<ConnectionState, PillState> = {
  disconnected: "OFFLINE",
  connecting: "CONNECTING",
  connected: "CONNECTING",
  ready: "LIVE",
  reconnecting: "RECONNECTING",
};

const PILL_DOT_CLASS: Record<PillState, string> = {
  LIVE: "on",
  CONNECTING: "pending",
  RECONNECTING: "pending",
  OFFLINE: "error",
};

type Mode = "TEXT" | "VOICE" | "HYBRID";
const MODES: Mode[] = ["TEXT", "VOICE", "HYBRID"];

function useClock(): string {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  const pad = (n: number) => n.toString().padStart(2, "0");
  return `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
}

export function TopBar() {
  const connection = useStore((s) => s.connection);
  const pill = PILL_MAP[connection];
  const clock = useClock();
  // Local UI preference only — no backend concept of "mode"; does not gate
  // which panels receive real data (all panels always reflect real events).
  const [mode, setMode] = useState<Mode>("HYBRID");

  return (
    <header className="console-panel topbar">
      <span className="topbar-wordmark">
        ROBO://
        <span className="topbar-cursor" aria-hidden="true" />
      </span>

      <span className="topbar-conn">
        <span className={`status-dot ${PILL_DOT_CLASS[pill]}`} />
        <span>{pill}</span>
      </span>

      <span className="topbar-spacer" />

      <span className="topbar-clock">{clock}</span>

      <span className="topbar-mode" role="group" aria-label="Interaction mode">
        {MODES.map((m) => (
          <button
            key={m}
            type="button"
            className={`mode-btn ${mode === m ? "active" : ""}`}
            aria-pressed={mode === m}
            onClick={() => setMode(m)}
          >
            {m}
          </button>
        ))}
      </span>
    </header>
  );
}
