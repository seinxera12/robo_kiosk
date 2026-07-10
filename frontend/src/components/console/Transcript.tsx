import { useEffect, useRef, useState } from "react";
import { useStore } from "../../store/useStore";

/**
 * Center panel — conversation transcript as terminal scrollback (spec §3.3).
 * Reads the existing `bubbles` store (FE-4/FE-5 — unchanged); this is a
 * presentational reskin, not a new data path. Auto-scrolls to bottom on new
 * content, but pauses if the user has scrolled up, resuming via a "new
 * messages" pill.
 */

function formatTime(ts: number): string {
  const d = new Date(ts);
  const pad = (n: number) => n.toString().padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

const NEAR_BOTTOM_PX = 48;

export function Transcript() {
  const bubbles = useStore((s) => s.bubbles);
  const status = useStore((s) => s.status);
  const bodyRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);

  // "Speaking" highlight (spec §3.3): line-level only — the backend sends no
  // word-boundary timing metadata, so per-word highlighting is out of scope
  // (spec §9). The most recent assistant bubble is the one TTS is voicing;
  // text may finish streaming before audio drains (REF §3.5 #4 /
  // PlaybackTracker), so `status === "speaking"` — not `b.open` — gates this.
  const lastAssistantId = [...bubbles].reverse().find((b) => b.role === "assistant")?.id;

  useEffect(() => {
    const el = bodyRef.current;
    if (!el || !autoScroll) return;
    el.scrollTop = el.scrollHeight;
  }, [bubbles, autoScroll]);

  function handleScroll() {
    const el = bodyRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    setAutoScroll(distanceFromBottom <= NEAR_BOTTOM_PX);
  }

  function jumpToBottom() {
    const el = bodyRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
    setAutoScroll(true);
  }

  return (
    <section className="console-panel panel-center">
      <header className="console-panel-header">
        <span className="status-dot on" />
        Transcript
      </header>
      <div
        className="console-panel-body transcript-body"
        role="log"
        aria-live="polite"
        ref={bodyRef}
        onScroll={handleScroll}
      >
        {bubbles.length === 0 && (
          <p className="transcript-empty">
            Say something or type a message to begin.
          </p>
        )}
        {bubbles.map((b) => {
          const speaking = status === "speaking" && b.id === lastAssistantId;
          return (
            <div
              key={b.id}
              className={`log-line log-line-${b.role} ${speaking ? "log-line-speaking" : ""}`}
            >
              <span className="log-ts">[{formatTime(b.ts)}]</span>{" "}
              <span className="log-actor">{b.role === "user" ? "USER" : "ROBO"}</span>{" "}
              <span className="log-arrow">&gt;</span>{" "}
              <span className="log-text">{b.text}</span>
              {b.open && (
                <span className="log-cursor" aria-hidden="true">
                  ▌
                </span>
              )}
            </div>
          );
        })}
      </div>
      {!autoScroll && (
        <button type="button" className="scroll-pill" onClick={jumpToBottom}>
          new messages ↓
        </button>
      )}
    </section>
  );
}
