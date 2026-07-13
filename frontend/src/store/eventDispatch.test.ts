import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { dispatchEvent, resetTurnTrace } from "./eventDispatch";
import { _resetStore, getSnapshot } from "./store";

/**
 * Tokens are not written to the store synchronously: dispatchEvent queues them
 * and a timer drains one per TOKEN_DRAIN_INTERVAL_MS, holding final:true until
 * the queue empties. These tests therefore drive the clock rather than assert
 * straight after dispatch. `drain()` runs the queue to completion.
 */
const DRAIN_INTERVAL_MS = 100;

function drain(): void {
  vi.advanceTimersByTime(DRAIN_INTERVAL_MS * 20);
}

describe("bubble gating + streaming (FE-4, REF §3.9.5, §3.4)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    _resetStore();
    // Clear any queue/timer left behind by a previous test (module-level state).
    resetTurnTrace();
  });

  afterEach(() => {
    resetTurnTrace();
    vi.useRealTimers();
  });

  it("concatenates tokens verbatim with no inserted spaces", () => {
    dispatchEvent({ kind: "llm_text_chunk", text: "The cafeteria ", final: false });
    dispatchEvent({ kind: "llm_text_chunk", text: "is ", final: false });
    dispatchEvent({ kind: "llm_text_chunk", text: "downstairs.", final: false });
    dispatchEvent({ kind: "llm_text_chunk", text: "", final: true });
    drain();

    const { bubbles } = getSnapshot();
    expect(bubbles).toHaveLength(1);
    expect(bubbles[0].role).toBe("assistant");
    expect(bubbles[0].text).toBe("The cafeteria is downstairs.");
    expect(bubbles[0].open).toBe(false);
  });

  it("a lone final:true while idle produces NO bubble (REF §3.9.5)", () => {
    dispatchEvent({ kind: "llm_text_chunk", text: "", final: true });
    drain();
    expect(getSnapshot().bubbles).toHaveLength(0);
    expect(getSnapshot().responseStarted).toBe(false);
  });

  it("opens the bubble only on the first non-empty token", () => {
    dispatchEvent({ kind: "llm_text_chunk", text: "", final: false });
    drain();
    expect(getSnapshot().bubbles).toHaveLength(0);

    dispatchEvent({ kind: "llm_text_chunk", text: "Hi", final: false });
    // Still nothing until the drain timer ticks — the bubble opens on render.
    expect(getSnapshot().bubbles).toHaveLength(0);
    drain();
    expect(getSnapshot().bubbles).toHaveLength(1);
  });

  it("renders a voice transcript as a user bubble and sets thinking", () => {
    dispatchEvent({ kind: "transcript", text: "Where is the exit?", lang: "en", final: true });
    const { bubbles, status } = getSnapshot();
    expect(bubbles).toHaveLength(1);
    expect(bubbles[0].role).toBe("user");
    expect(status).toBe("thinking");
  });

  it("maps status events and token flow to pipeline status", () => {
    // `speaking` is set eagerly when the token arrives, not on render.
    dispatchEvent({ kind: "llm_text_chunk", text: "Hi", final: false });
    expect(getSnapshot().status).toBe("speaking");

    // final:true is held until the queue drains, so the turn stays `speaking`
    // while text is still rendering, and only returns to `listening` after.
    dispatchEvent({ kind: "llm_text_chunk", text: "", final: true });
    expect(getSnapshot().status).toBe("speaking");
    drain();
    expect(getSnapshot().status).toBe("listening");

    dispatchEvent({ kind: "status", state: "listening" });
    expect(getSnapshot().status).toBe("listening");
  });
});
