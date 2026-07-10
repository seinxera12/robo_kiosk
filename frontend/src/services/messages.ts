/**
 * WebSocket message catalog (FE-2).
 *
 * Typed encode/decode for the complete protocol (REF §4.2, §3.3, §3.4).
 * The wire discriminates by frame kind first (binary = audio, text = JSON),
 * then by the JSON `type` field.
 *
 * Contract invariants enforced here:
 *  - llm_text_chunk.text is preserved VERBATIM, including leading/trailing
 *    spaces — callers must concatenate without inserting spaces (REF §3.4).
 *  - Unknown JSON `type` decodes to a benign {kind:"unknown"} variant; the
 *    server likewise ignores unknown types (REF §4.2).
 *  - Language is always sent as "auto"; the server re-detects (REF §3.3.2, #8).
 */

// ----------------------------- Client -> Server -----------------------------

export type Lang = "en" | "ja" | "auto";

export interface SessionStartMsg {
  type: "session_start";
  kiosk_id: string;
  kiosk_location: string;
}

export interface TextInputMsg {
  type: "text_input";
  text: string;
  lang: Lang;
}

export interface InterruptMsg {
  type: "interrupt";
}

export interface SessionResetMsg {
  type: "session_reset";
}

export type OutboundMsg =
  | SessionStartMsg
  | TextInputMsg
  | InterruptMsg
  | SessionResetMsg;

// ----------------------------- Server -> Client -----------------------------

export interface SessionAckEvent {
  kind: "session_ack";
  status: string; // "ready"
}

export interface TranscriptEvent {
  kind: "transcript";
  text: string;
  lang: string; // "en" | "ja"
  final: boolean; // always true from server, kept for fidelity
}

export interface LlmTextChunkEvent {
  kind: "llm_text_chunk";
  text: string; // verbatim token/delta; may be "" (esp. on final)
  final: boolean;
}

export interface StatusEvent {
  kind: "status";
  state: string; // e.g. "listening"
}

/** Any binary frame — a WAV/PCM slice (REF §4.2, §5.3). */
export interface AudioFrameEvent {
  kind: "audio";
  data: ArrayBuffer;
}

/** Unrecognized JSON type — retained but inert (REF §4.2). */
export interface UnknownEvent {
  kind: "unknown";
  type: string;
  raw: unknown;
}

/** A JSON frame that failed to parse. */
export interface MalformedEvent {
  kind: "malformed";
  raw: string;
}

export type InboundEvent =
  | SessionAckEvent
  | TranscriptEvent
  | LlmTextChunkEvent
  | StatusEvent
  | AudioFrameEvent
  | UnknownEvent
  | MalformedEvent;

// ------------------------------- Boilerplate --------------------------------

/**
 * Defensive strip of language-instruction boilerplate that the server SHOULD
 * have removed but might leak if a regex variant is missed (REF §3.5, #15).
 * Applied to transcript/chunk text before display.
 */
const BOILERPLATE_PATTERNS: RegExp[] = [
  /\[Reply in English\]/gi,
  /\[Reply in Japanese\]/gi,
  /\[日本語で回答してください\]/g,
  /\[英語で回答してください\]/g,
];

export function stripBoilerplate(text: string): string {
  let out = text;
  for (const re of BOILERPLATE_PATTERNS) {
    out = out.replace(re, "");
  }
  return out;
}

// -------------------------------- Encoding ----------------------------------

export function encodeSessionStart(
  kioskId: string,
  kioskLocation: string
): string {
  return JSON.stringify({
    type: "session_start",
    kiosk_id: kioskId,
    kiosk_location: kioskLocation,
  } satisfies SessionStartMsg);
}

/** Always send lang:"auto" — server is authoritative (REF §3.3.2, #8). */
export function encodeTextInput(text: string, lang: Lang = "auto"): string {
  return JSON.stringify({ type: "text_input", text, lang } satisfies TextInputMsg);
}

export function encodeInterrupt(): string {
  return JSON.stringify({ type: "interrupt" } satisfies InterruptMsg);
}

export function encodeSessionReset(): string {
  return JSON.stringify({ type: "session_reset" } satisfies SessionResetMsg);
}

// -------------------------------- Decoding ----------------------------------

/**
 * Decode one inbound WebSocket frame. `data` is whatever `MessageEvent.data`
 * yields for a socket with binaryType="arraybuffer": either a string (JSON
 * event) or an ArrayBuffer (audio). ArrayBufferView is also tolerated.
 */
export function decodeInbound(data: unknown): InboundEvent {
  if (data instanceof ArrayBuffer) {
    return { kind: "audio", data };
  }
  if (ArrayBuffer.isView(data)) {
    const view = data as ArrayBufferView;
    // Copy into a fresh (non-shared) ArrayBuffer.
    const copy = new ArrayBuffer(view.byteLength);
    new Uint8Array(copy).set(
      new Uint8Array(view.buffer, view.byteOffset, view.byteLength)
    );
    return { kind: "audio", data: copy };
  }
  if (typeof data === "string") {
    return decodeJson(data);
  }
  return { kind: "malformed", raw: String(data) };
}

function decodeJson(raw: string): InboundEvent {
  let parsed: Record<string, unknown>;
  try {
    parsed = JSON.parse(raw) as Record<string, unknown>;
  } catch {
    return { kind: "malformed", raw };
  }

  const type = parsed.type;
  switch (type) {
    case "session_ack":
      return { kind: "session_ack", status: str(parsed.status, "ready") };

    case "transcript":
      return {
        kind: "transcript",
        text: stripBoilerplate(str(parsed.text, "")),
        lang: str(parsed.lang, ""),
        final: bool(parsed.final, true),
      };

    case "llm_text_chunk":
      return {
        kind: "llm_text_chunk",
        // Verbatim — do NOT trim (REF §3.4). Only strip leaked boilerplate.
        text: stripBoilerplate(str(parsed.text, "")),
        final: bool(parsed.final, false),
      };

    case "status":
      return { kind: "status", state: str(parsed.state, "") };

    default:
      return { kind: "unknown", type: str(type, ""), raw: parsed };
  }
}

function str(v: unknown, fallback: string): string {
  return typeof v === "string" ? v : fallback;
}

function bool(v: unknown, fallback: boolean): boolean {
  return typeof v === "boolean" ? v : fallback;
}
