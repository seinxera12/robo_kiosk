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
 * Hooks (set by later tasks): onResponseActivity fires on any token/transcript
 * so TimeoutGuard (FE-13) can cancel its timer; onFinal fires on final:true.
 */
import type { InboundEvent } from "../services/messages";
import { actions } from "./store";
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

export function dispatchEvent(ev: InboundEvent, hooks: DispatchHooks = {}): void {
  switch (ev.kind) {
    case "session_ack":
      hooks.onReady?.();
      break;

    case "transcript":
      // Voice path: render the user's transcribed utterance (REF §3.4).
      hooks.onResponseActivity?.();
      if (ev.text.length > 0) actions.addUserBubble(ev.text);
      actions.setStatus("thinking");
      break;

    case "llm_text_chunk":
      hooks.onResponseActivity?.();
      if (ev.text.length > 0) {
        actions.appendAssistantToken(ev.text);
        actions.setStatus("speaking");
      }
      if (ev.final) {
        // Close only if a bubble opened (REF §3.9.5); no-op otherwise.
        actions.finishAssistantResponse();
        actions.setStatus("listening");
        hooks.onFinal?.();
      }
      break;

    case "status": {
      const mapped = mapServerState(ev.state);
      if (mapped) actions.setStatus(mapped);
      break;
    }

    case "audio":
    case "unknown":
    case "malformed":
      // audio handled by ConnectionManager's onAudio; unknown/malformed inert.
      break;
  }
}
