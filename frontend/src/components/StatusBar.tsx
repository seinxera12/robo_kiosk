import { useStore } from "../store/useStore";
import type { SessionController } from "../services/SessionController";
import type { ConnectionState, PipelineStatus } from "../store/types";

/**
 * Status bar (FE-15 connection indicator + FE-10 interrupt + FE-14 clear).
 * Shows live connection state and pipeline status; hosts the Interrupt and
 * Clear-conversation actions.
 */

const CONNECTION_LABEL: Record<ConnectionState, string> = {
  disconnected: "Disconnected",
  connecting: "Connecting…",
  connected: "Handshaking…",
  ready: "Connected",
  reconnecting: "Reconnecting…",
};

const STATUS_LABEL: Record<PipelineStatus, string> = {
  idle: "Idle",
  listening: "Ready",
  thinking: "Thinking…",
  speaking: "Speaking…",
};

export function StatusBar({ controller }: { controller: SessionController | null }) {
  const connection = useStore((s) => s.connection);
  const status = useStore((s) => s.status);
  const ready = connection === "ready";
  const busy = status === "thinking" || status === "speaking";

  return (
    <div className="status-bar">
      <span className={`conn-dot conn-${connection}`} aria-hidden="true" />
      <span className="conn-label">{CONNECTION_LABEL[connection]}</span>
      <span className="status-label">{STATUS_LABEL[status]}</span>
      <span className="spacer" />
      <button
        type="button"
        disabled={!controller || !ready || !busy}
        onClick={() => controller?.interrupt()}
      >
        Interrupt
      </button>
      <button
        type="button"
        disabled={!controller || !ready}
        onClick={() => controller?.clearConversation()}
      >
        Clear
      </button>
    </div>
  );
}
