import { useEffect, useRef, useState } from "react";
import { useStore } from "../../store/useStore";
import type { VoiceController } from "../../audio/VoiceController";
import { useDefaultCollapsed } from "./useDefaultCollapsed";

/**
 * Left panel — Input Visualizer (spec §3.2).
 *
 * The backend has no `mic:level` or `stt:partial` event (REF messages.ts):
 * STT only ever arrives as a final `transcript` event, no incremental text.
 * So this panel shows only what's real: local mic amplitude (via
 * VoiceController.onLevel, tapped from the existing capture frame stream)
 * and the most recent final transcript as a brief flash — no fabricated
 * in-progress partial line (spec §4, §9: don't invent events).
 */

const BAR_COUNT = 40;
const SPEECH_THRESHOLD = 0.02;
const IDLE_BREATH_PERIOD_MS = 2200;
const FLASH_MS = 2500;

// Spec §3.2 lists a `muted` state distinct from `idle`, but the store's
// RecordingMode (idle | alwaysListen | manualSpeak) has no separate "muted"
// concept — mic-off IS idle here. Modeling both would fabricate a
// distinction the app doesn't have, so `idle` covers both "mic off" and
// "explicitly muted."
type VisState = "idle" | "listening" | "speech_detected";

export function InputVisualizer({ voice }: { voice: VoiceController }) {
  const recording = useStore((s) => s.recording);
  const bubbles = useStore((s) => s.bubbles);
  const [level, setLevel] = useState(0);
  const [breath, setBreath] = useState(0);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    const unsub = voice.onLevel(setLevel);
    return unsub;
  }, [voice]);

  // Idle "breathing" animation, disabled under prefers-reduced-motion.
  useEffect(() => {
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduceMotion) return;
    let start: number | null = null;
    function tick(t: number) {
      if (start === null) start = t;
      const phase = ((t - start) % IDLE_BREATH_PERIOD_MS) / IDLE_BREATH_PERIOD_MS;
      setBreath(0.5 + 0.5 * Math.sin(phase * Math.PI * 2));
      rafRef.current = requestAnimationFrame(tick);
    }
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
  }, []);

  const micOpen = recording !== "idle";
  const speaking = micOpen && level > SPEECH_THRESHOLD;

  const state: VisState = !micOpen ? "idle" : speaking ? "speech_detected" : "listening";

  // Most recent user (transcript) bubble, flashed briefly under the waveform.
  const lastUserText = [...bubbles].reverse().find((b) => b.role === "user")?.text;
  const [flashText, setFlashText] = useState<string | null>(null);
  useEffect(() => {
    if (!lastUserText) return;
    setFlashText(lastUserText);
    const id = setTimeout(() => setFlashText(null), FLASH_MS);
    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bubbles.length]);

  const bars = Array.from({ length: BAR_COUNT }, (_, i) => {
    if (!micOpen) return 0.04;
    if (speaking) {
      // Deterministic per-bar jitter around the live level so bars aren't
      // perfectly uniform, without fabricating per-frequency-bin data we
      // don't have (there's no AnalyserNode; this is RMS-only).
      const jitter = 0.6 + 0.4 * Math.abs(Math.sin(i * 12.9898 + level * 78.233));
      return Math.min(1, level * 6 * jitter);
    }
    // idle-open breathing
    const wave = 0.15 + 0.1 * breath * Math.abs(Math.sin(i * 0.7 + breath * 3));
    return wave;
  });

  const [collapsed, setCollapsed] = useDefaultCollapsed();

  return (
    <section className={`console-panel panel-left ${collapsed ? "is-collapsed" : ""}`}>
      <button
        type="button"
        className="console-panel-header accordion-toggle"
        onClick={() => setCollapsed((c) => !c)}
        aria-expanded={!collapsed}
      >
        <span className={`status-dot ${micOpen ? (speaking ? "on" : "pending") : ""}`} />
        Mic Input
        <span className="mic-level-num">
          {micOpen ? `${Math.round(Math.min(1, level * 6) * 100)}` : "0"}
        </span>
        <span className="accordion-chevron" aria-hidden="true">
          {collapsed ? "▸" : "▾"}
        </span>
      </button>
      <div className={`console-panel-body input-visualizer vis-${state}`}>
        <div className="waveform" aria-hidden="true">
          {bars.map((h, i) => (
            <span key={i} className="bar" style={{ height: `${Math.max(4, h * 100)}%` }} />
          ))}
        </div>
        {!micOpen && <p className="vis-idle-label">MIC OFF</p>}
        {flashText && micOpen && <p className="stt-flash">{flashText}</p>}
      </div>
    </section>
  );
}
