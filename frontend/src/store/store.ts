/**
 * Central app store (plan §4.1 — small store, no external lib).
 *
 * A single immutable state object with subscribe/getSnapshot so React can bind
 * via useSyncExternalStore. Services (ConnectionManager, AudioPlayer, …) call
 * the action methods; components read via the hook in ./useStore.
 *
 * Bubble gating (REF §3.9.5): the assistant bubble opens on the first NON-EMPTY
 * llm_text_chunk and closes on final:true ONLY if one was opened — so a lone
 * final:true while idle produces no phantom bubble.
 */
import type {
  Bubble,
  ConnectionState,
  PipelineStatus,
  RecordingMode,
} from "./types";

export interface AppState {
  connection: ConnectionState;
  status: PipelineStatus;
  recording: RecordingMode;
  bubbles: Bubble[];
  /** True while an assistant bubble is open and accepting tokens. */
  responseStarted: boolean;
  /** Soft error banner text (FE-13), or null. */
  softError: string | null;
  /** Last /health body (FE-15), or null. */
  health: unknown | null;
}

const initialState: AppState = {
  connection: "disconnected",
  status: "idle",
  recording: "idle",
  bubbles: [],
  responseStarted: false,
  softError: null,
  health: null,
};

type Listener = () => void;

let state: AppState = initialState;
const listeners = new Set<Listener>();

let bubbleSeq = 0;
function nextId(): string {
  bubbleSeq += 1;
  return `b${bubbleSeq}`;
}

function set(patch: Partial<AppState>): void {
  state = { ...state, ...patch };
  for (const l of listeners) l();
}

export function getSnapshot(): AppState {
  return state;
}

export function subscribe(l: Listener): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}

// ------------------------------- Actions ------------------------------------

export const actions = {
  setConnection(connection: ConnectionState): void {
    set({ connection });
  },

  setStatus(status: PipelineStatus): void {
    set({ status });
  },

  setRecording(recording: RecordingMode): void {
    set({ recording });
  },

  setHealth(health: unknown | null): void {
    set({ health });
  },

  setSoftError(softError: string | null): void {
    set({ softError });
  },

  /** Add a user bubble (typed local echo — REF §3.3.2 — or voice transcript). */
  addUserBubble(text: string): void {
    const bubble: Bubble = { id: nextId(), role: "user", text, open: false };
    set({ bubbles: [...state.bubbles, bubble] });
  },

  /**
   * Append a streamed assistant token (REF §3.4). Opens a bubble on the first
   * non-empty token (REF §3.9.5). Empty tokens are ignored for gating but do
   * not create bubbles.
   */
  appendAssistantToken(text: string): void {
    if (text.length === 0) return;
    if (!state.responseStarted) {
      const bubble: Bubble = {
        id: nextId(),
        role: "assistant",
        text,
        open: true,
      };
      set({ bubbles: [...state.bubbles, bubble], responseStarted: true });
      return;
    }
    const bubbles = state.bubbles.slice();
    // The open assistant bubble is the last one.
    for (let i = bubbles.length - 1; i >= 0; i--) {
      if (bubbles[i].role === "assistant" && bubbles[i].open) {
        bubbles[i] = { ...bubbles[i], text: bubbles[i].text + text };
        break;
      }
    }
    set({ bubbles });
  },

  /**
   * Close the current assistant bubble on final:true — but ONLY if a bubble was
   * opened (REF §3.9.5). A lone final:true while idle is a no-op.
   */
  finishAssistantResponse(): void {
    if (!state.responseStarted) return;
    const bubbles = state.bubbles.map((b) =>
      b.role === "assistant" && b.open ? { ...b, open: false } : b
    );
    set({ bubbles, responseStarted: false });
  },

  /** Clear all local bubbles (FE-14). */
  clearBubbles(): void {
    set({ bubbles: [], responseStarted: false });
  },
};

/** Test-only reset. */
export function _resetStore(): void {
  state = initialState;
  bubbleSeq = 0;
  listeners.clear();
}
