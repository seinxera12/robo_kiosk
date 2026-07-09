import { useStore } from "../store/useStore";
import type { VoiceController } from "../audio/VoiceController";

/**
 * Mic controls (FE-9 voice send). Push-to-talk (guaranteed path) plus an
 * always-listen toggle. Pressing to talk while the assistant speaks triggers
 * server barge-in via the new utterance (REF §3.6); local audio flush happens
 * in sendUtterance (FE-11).
 */
export function MicButton({ voice }: { voice: VoiceController }) {
  const ready = useStore((s) => s.connection === "ready");
  const recording = useStore((s) => s.recording);
  const alwaysOn = recording === "alwaysListen";

  return (
    <div className="mic-controls">
      <button
        type="button"
        className={`ptt ${recording === "manualSpeak" ? "recording" : ""}`}
        disabled={!ready || alwaysOn}
        onPointerDown={() => void voice.pressToTalk()}
        onPointerUp={() => voice.releaseToTalk()}
        onPointerLeave={() => recording === "manualSpeak" && voice.releaseToTalk()}
      >
        {recording === "manualSpeak" ? "Listening…" : "Hold to speak"}
      </button>
      <label className="always-listen">
        <input
          type="checkbox"
          checked={alwaysOn}
          disabled={!ready}
          onChange={(e) =>
            e.target.checked
              ? void voice.enableAlwaysListen()
              : voice.disableAlwaysListen()
          }
        />
        Auto-listen
      </label>
    </div>
  );
}
