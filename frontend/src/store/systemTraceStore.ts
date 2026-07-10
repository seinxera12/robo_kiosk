/**
 * System trace log (spec §3.4). A capped, append-only array of real pipeline
 * events — connection lifecycle, transcript/token/status events actually
 * emitted by the backend (REF messages.ts). No fabricated stages: the
 * backend has no granular "llm: request sent" / "tts: synthesizing" events,
 * only session_ack, transcript, llm_text_chunk, status, and binary audio
 * frames, so only lines with real triggers are ever appended (wired in
 * eventDispatch.ts and ConnectionManager.ts).
 */

export type TraceGlyph = "pending" | "active" | "done" | "error";

export interface TraceLine {
  id: number;
  ts: number;
  glyph: TraceGlyph;
  text: string;
}

const MAX_LINES = 200;

let lines: TraceLine[] = [];
let seq = 0;

type Listener = () => void;
const listeners = new Set<Listener>();

export function getTraceSnapshot(): TraceLine[] {
  return lines;
}

export function subscribeTrace(l: Listener): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}

export function appendTrace(glyph: TraceGlyph, text: string): void {
  seq += 1;
  const line: TraceLine = { id: seq, ts: Date.now(), glyph, text };
  lines = [...lines, line];
  if (lines.length > MAX_LINES) lines = lines.slice(lines.length - MAX_LINES);
  for (const l of listeners) l();
}

/** Test-only reset. */
export function _resetTraceStore(): void {
  lines = [];
  seq = 0;
  listeners.clear();
}
