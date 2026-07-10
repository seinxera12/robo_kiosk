import { useState } from "react";
import { useStore } from "../../store/useStore";
import type { SessionController } from "../../services/SessionController";
import type { VoiceController } from "../../audio/VoiceController";
import type { AudioPlayer } from "../../audio/AudioPlayer";

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
}: {
  controller: SessionController;
  voice: VoiceController;
  player: AudioPlayer;
}) {
  const [value, setValue] = useState("");
  const [muted, setMuted] = useState(false);
  const ready = useStore((s) => s.connection === "ready");
  const streaming = useStore((s) => s.responseStarted);
  const recording = useStore((s) => s.recording);
  const micLive = recording === "alwaysListen";

  // Block text send while the assistant is still streaming tokens.
  // Voice barge-in (MIC toggle) is intentionally left unrestricted — that
  // path goes through VoiceController and is a separate interaction contract.
  const canSend = ready && !streaming;

  function submit() {
    if (!canSend) return;
    if (controller.sendText(value)) setValue("");
  }

  function toggleMic() {
    if (micLive) {
      voice.disableAlwaysListen();
    } else {
      void voice.enableAlwaysListen();
    }
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
        className={`composer-mic ${micLive ? "live" : ""}`}
        disabled={!ready}
        aria-pressed={micLive}
        aria-label={micLive ? "Disable microphone" : "Enable microphone"}
        onClick={toggleMic}
      >
        {micLive ? "● MIC LIVE" : "○ MIC OFF"}
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
