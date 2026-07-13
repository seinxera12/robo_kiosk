/**
 * Event dispatcher (FE-4).
 *
 * Maps decoded inbound JSON events to store mutations + pipeline status
 * transitions (REF §8, §3.4). This is the single place server events become
 * UI state, so bubble gating and status stay consistent.
 *
 * Status mapping (advisory, server-authoritative — REF §8):
 *   transcript          -> thinking (STT done, awaiting LLM)
 *   first non-empty token-> speaking
 *   llm_text_chunk final -> listening
 *   status{state}        -> mapped directly
 *
 * Token render throttle: tokens are queued and drained at TOKEN_DRAIN_INTERVAL_MS
 * (≈25% slower than raw websocket delivery) so the text stream feels readable
 * rather than instantaneous. The final:true signal is held until the queue is
 * fully drained so the bubble never closes mid-stream.
 *
 * Hooks (set by later tasks): onResponseActivity fires on any token/transcript
 * so TimeoutGuard (FE-13) can cancel its timer; onFinal fires on final:true.
 */
import type { InboundEvent } from "../services/messages";
import { actions } from "./store";
import { appendTrace } from "./systemTraceStore";
import type { PipelineStatus } from "./types";

export interface DispatchHooks {
  /** Any inbound sign the current turn is alive (cancels FE-13 timeout). */
  onResponseActivity?: () => void;
  /** A turn's text stream ended (final:true and a bubble had opened). */
  onFinal?: () => void;
  /** session_ack received. */
  onReady?: () => void;
  /** A client request (text or voice) was just sent — arms FE-13 timeout. */
  onSend?: () => void;
}

function mapServerState(state: string): PipelineStatus | null {
  switch (state) {
    case "idle":
    case "listening":
    case "thinking":
    case "speaking":
      return state;
    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// Token render throttle
// Tokens arrive from the websocket faster than a human reads. We queue them
// and drain at TOKEN_DRAIN_INTERVAL_MS — roughly 25% slower than the median
// raw delivery cadence. Adjust the constant to taste.
// ---------------------------------------------------------------------------

/** ms between each queued token being pushed to the store / rendered. */
const TOKEN_DRAIN_INTERVAL_MS = 100;

const tokenQueue: string[] = [];
let drainTimer: ReturnType<typeof setInterval> | null = null;
let pendingFinal = false;
let pendingHooks: DispatchHooks = {};

function startDrain(): void {
  if (drainTimer !== null) return;
  drainTimer = setInterval(() => {
    const chunk = tokenQueue.shift();
    if (chunk !== undefined) {
      actions.appendAssistantToken(chunk);
    }
    if (tokenQueue.length === 0 && pendingFinal) {
      // Queue fully drained — now safe to close the bubble.
      stopDrain();
      appendTrace("done", "llm: response complete");
      tokenStreamTraced = false;
      actions.finishAssistantResponse();
      actions.setStatus("listening");
      pendingHooks.onFinal?.();
      pendingFinal = false;
      pendingHooks = {};
    }
  }, TOKEN_DRAIN_INTERVAL_MS);
}

function stopDrain(): void {
  if (drainTimer !== null) {
    clearInterval(drainTimer);
    drainTimer = null;
  }
}

/** Flush the queue immediately (called on barge-in / new turn). */
function flushTokenQueue(): void {
  tokenQueue.length = 0;
  pendingFinal = false;
  pendingHooks = {};
  stopDrain();
}

// Tracks whether the current turn's first token has already been traced, so
// SystemTrace logs one "streaming" line per turn rather than one per token
// (spec §3.4: compact log lines). The audio equivalent lives in PlaybackTracker,
// which is the module binary frames actually reach.
let tokenStreamTraced = false;

export function dispatchEvent(ev: InboundEvent, hooks: DispatchHooks = {}): void {
  switch (ev.kind) {
    case "session_ack":
      appendTrace("done", "session ack received");
      hooks.onReady?.();
      break;

    case "transcript":
      // Voice path: render the user's transcribed utterance (REF §3.4).
      appendTrace("done", "stt: final transcript received");
      hooks.onResponseActivity?.();
      if (ev.text.length > 0) actions.addUserBubble(ev.text);
      actions.setStatus("thinking");
      break;

    case "llm_text_chunk":
      hooks.onResponseActivity?.();
      if (ev.text.length > 0) {
        if (!tokenStreamTraced) {
          appendTrace("active", "llm: streaming tokens...");
          tokenStreamTraced = true;
        }
        // Queue for throttled render rather than direct store write.
        actions.setStatus("speaking");
        tokenQueue.push(ev.text);
        startDrain();
      }
      if (ev.final) {
        // Don't close the bubble yet — hold until the queue drains.
        pendingFinal = true;
        pendingHooks = hooks;
        // If the queue is already empty (e.g. empty final frame), the drain
        // timer will handle it on the next tick; if not running, start it.
        startDrain();
      }
      break;

    case "status": {
      const mapped = mapServerState(ev.state);
      if (mapped) actions.setStatus(mapped);
      break;
    }

    case "audio":
      // Unreachable: ConnectionManager sends binary frames straight to the
      // audio sink and returns without calling dispatchEvent. The first-frame
      // trace lives in PlaybackTracker.onAudioFrame, which IS on that path.
      break;

    case "unknown":
    case "malformed":
      // Inert per REF §4.2 — not traced (would misrepresent real pipeline state).
      break;
  }
}

/**
 * Reset per-turn trace throttling. Called on barge-in/new-turn boundaries
 * (SessionController.sendText/sendUtterance) so the next response's first
 * token/audio frame is traced again. "tts: playback complete" is traced
 * separately by PlaybackTracker, the module that actually knows when audio
 * has drained (REF §3.5, #4 — there is no end-of-audio socket event).
 */
export function resetTurnTrace(): void {
  tokenStreamTraced = false;
  // Also flush any queued tokens from the previous turn so a barge-in starts
  // clean and the old bubble doesn't continue rendering after interruption.
  flushTokenQueue();
}
