import { useEffect, useState } from "react";
import { useStore } from "../../store/useStore";
import type { SessionController } from "../../services/SessionController";
import type { VoiceController } from "../../audio/VoiceController";
import type { AudioPlayer } from "../../audio/AudioPlayer";
import type { HealthGate } from "../../services/useHealthGate";

/**
 * Bottom bar — Composer (spec §3.5). Terminal-prompt text input, full-duplex
 * mic toggle (push-to-toggle, not push-to-talk — voice can barge in any time),
 * and a TTS mute toggle. Reuses SessionController.sendText and
 * VoiceController.enableAlwaysListen/disableAlwaysListen unchanged — this is
 * a visual replacement for MinimalComposer/MicButton, not a new send/mic path.
 */
export function Composer({
  controller,
  voice,
  player,
  health,
}: {
  controller: SessionController;
  voice: VoiceController;
  player: AudioPlayer;
  health: HealthGate;
}) {
  const [value, setValue] = useState("");
  const [muted, setMuted] = useState(false);
  const ready = useStore((s) => s.connection === "ready");
  const streaming = useStore((s) => s.responseStarted);
  const recording = useStore((s) => s.recording);
  const micLive = recording === "alwaysListen";

  // The socket can be `ready` (session_ack received) while STT is still loading
  // on the server. Speaking into that drops the utterance, so the mic needs the
  // pipeline to be up — not just the connection (see services/health.ts).
  //
  // Text is deliberately NOT gated the same way: a warming server makes a typed
  // query slow, not lost, and locking the keyboard on a health endpoint that
  // could be unreachable for unrelated reasons would be a worse failure mode.
  const pipelineReady = health.phase === "ready";
  const canUseMic = ready && pipelineReady;

  // Don't strand a live mic if the pipeline drops out from under it.
  useEffect(() => {
    if (micLive && !canUseMic) voice.disableAlwaysListen();
  }, [micLive, canUseMic, voice]);

  // Block text send while the assistant is still streaming tokens.
  // Voice barge-in (MIC toggle) is intentionally left unrestricted — that
  // path goes through VoiceController and is a separate interaction contract.
  const canSend = ready && !streaming;

  function submit() {
    if (!canSend) return;
    if (controller.sendText(value)) setValue("");
  }

  function toggleMic() {
    if (!canUseMic) return;
    if (micLive) {
      voice.disableAlwaysListen();
    } else {
      void voice.enableAlwaysListen();
    }
  }

  /** Say why the mic is unavailable, rather than just grey it out. */
  function micLabel(): string {
    if (micLive) return "● MIC LIVE";
    if (!ready) return "○ MIC OFF";
    if (health.phase === "warming") return "○ WARMING UP";
    if (health.phase === "unreachable") return "○ MIC OFF";
    return "○ MIC OFF";
  }

  function toggleMute() {
    const next = !muted;
    setMuted(next);
    player.setMuted(next);
  }

  return (
    <div className="composer">
      <button
        type="button"
        className={`composer-mic ${micLive ? "live" : ""} ${
          ready && health.phase === "warming" ? "warming" : ""
        }`}
        disabled={!canUseMic}
        aria-pressed={micLive}
        aria-label={micLive ? "Disable microphone" : "Enable microphone"}
        title={
          ready && health.phase === "warming"
            ? `Server is still loading: ${health.pending.join(", ")}`
            : undefined
        }
        onClick={toggleMic}
      >
        {micLabel()}
      </button>

      <form
        className="composer-form"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <span className="composer-prompt">&gt;</span>
        <input
          type="text"
          value={value}
          placeholder={!ready ? "Connecting…" : "Type a message…"}
          disabled={!ready}
          onChange={(e) => setValue(e.target.value)}
          aria-label="Message"
        />
        <button type="submit" disabled={!canSend || value.trim().length === 0}>
          Send
        </button>
      </form>

      <button
        type="button"
        className={`composer-mute ${muted ? "muted" : ""}`}
        aria-pressed={muted}
        aria-label={muted ? "Unmute assistant voice" : "Mute assistant voice"}
        onClick={toggleMute}
      >
        {muted ? "🔇" : "🔊"}
      </button>
    </div>
  );
}
