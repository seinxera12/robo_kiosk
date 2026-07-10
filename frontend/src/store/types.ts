/**
 * Shared store types (plan §4.3). State mirrors the backend state machine
 * (REF §8); the client never invents pipeline state.
 */

/** Connection lifecycle (REF §3.2, §3.8). ready = after session_ack. */
export type ConnectionState =
  | "disconnected"
  | "connecting"
  | "connected" // socket open, session_start sent, awaiting ack
  | "ready" // session_ack received
  | "reconnecting";

/** Advisory pipeline status echoed/derived from server events (REF §8, §3.4). */
export type PipelineStatus = "idle" | "listening" | "thinking" | "speaking";

/** Recording mode (REF §5.2, §8). */
export type RecordingMode = "idle" | "alwaysListen" | "manualSpeak";

export type BubbleRole = "user" | "assistant";

export interface Bubble {
  id: string;
  role: BubbleRole;
  text: string;
  /** assistant bubble still receiving tokens (REF §3.9.5). */
  open: boolean;
  /** ms since epoch when the bubble was created; for display timestamps only. */
  ts: number;
}
