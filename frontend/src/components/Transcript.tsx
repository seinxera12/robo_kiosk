import { useEffect, useRef } from "react";
import { useStore } from "../store/useStore";

/**
 * Chat transcript (FE-4). Renders user/assistant bubbles from the store.
 * Tokens are already concatenated verbatim in the store (REF §3.4), so we
 * render `text` as-is (whitespace preserved via CSS).
 */
export function Transcript() {
  const bubbles = useStore((s) => s.bubbles);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [bubbles]);

  return (
    <div className="transcript" role="log" aria-live="polite">
      {bubbles.length === 0 && (
        <p className="transcript-empty">Say something or type a message to begin.</p>
      )}
      {bubbles.map((b) => (
        <div key={b.id} className={`bubble bubble-${b.role}`}>
          <span className="bubble-text">{b.text}</span>
          {b.open && <span className="bubble-cursor" aria-hidden="true">▍</span>}
        </div>
      ))}
      <div ref={endRef} />
    </div>
  );
}
