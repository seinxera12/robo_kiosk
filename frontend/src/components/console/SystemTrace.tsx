import { useEffect, useRef } from "react";
import { useSystemTrace } from "../../store/useSystemTrace";
import type { TraceGlyph } from "../../store/systemTraceStore";
import { useDefaultCollapsed } from "./useDefaultCollapsed";

/**
 * Right panel — System / Agent Trace (spec §3.4). Pure log renderer: no
 * business logic here, just render whatever systemTraceStore has recorded.
 * Every line corresponds to a real event the backend actually emitted or a
 * real connection-lifecycle transition (wired in eventDispatch.ts,
 * ConnectionManager.ts, PlaybackTracker.ts) — no fabricated pipeline stages
 * (spec §4, §9).
 */

const GLYPH_CHAR: Record<TraceGlyph, string> = {
  pending: "○",
  active: "▸",
  done: "✓",
  error: "✗",
};

function formatTime(ts: number): string {
  const d = new Date(ts);
  const pad = (n: number) => n.toString().padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

export function SystemTrace() {
  const lines = useSystemTrace();
  const bodyRef = useRef<HTMLDivElement>(null);
  const [collapsed, setCollapsed] = useDefaultCollapsed();

  useEffect(() => {
    const el = bodyRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [lines]);

  return (
    <section className={`console-panel panel-right ${collapsed ? "is-collapsed" : ""}`}>
      <button
        type="button"
        className="console-panel-header accordion-toggle"
        onClick={() => setCollapsed((c) => !c)}
        aria-expanded={!collapsed}
      >
        <span className="status-dot on" />
        System Trace
        <span className="accordion-chevron" aria-hidden="true">
          {collapsed ? "▸" : "▾"}
        </span>
      </button>
      <div className="console-panel-body system-trace-body" ref={bodyRef}>
        {lines.length === 0 && <p className="trace-empty">No events yet.</p>}
        {lines.map((l) => (
          <div key={l.id} className={`trace-line trace-${l.glyph}`}>
            <span className="trace-glyph">{GLYPH_CHAR[l.glyph]}</span>{" "}
            <span className="trace-text">{l.text}</span>{" "}
            <span className="trace-ts">{formatTime(l.ts)}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
