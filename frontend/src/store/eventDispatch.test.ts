import { beforeEach, describe, expect, it } from "vitest";
import { dispatchEvent } from "./eventDispatch";
import { _resetStore, getSnapshot } from "./store";

describe("bubble gating + streaming (FE-4, REF §3.9.5, §3.4)", () => {
  beforeEach(() => _resetStore());

  it("concatenates tokens verbatim with no inserted spaces", () => {
    dispatchEvent({ kind: "llm_text_chunk", text: "The cafeteria ", final: false });
    dispatchEvent({ kind: "llm_text_chunk", text: "is ", final: false });
    dispatchEvent({ kind: "llm_text_chunk", text: "downstairs.", final: false });
    dispatchEvent({ kind: "llm_text_chunk", text: "", final: true });

    const { bubbles } = getSnapshot();
    expect(bubbles).toHaveLength(1);
    expect(bubbles[0].role).toBe("assistant");
    expect(bubbles[0].text).toBe("The cafeteria is downstairs.");
    expect(bubbles[0].open).toBe(false);
  });

  it("a lone final:true while idle produces NO bubble (REF §3.9.5)", () => {
    dispatchEvent({ kind: "llm_text_chunk", text: "", final: true });
    expect(getSnapshot().bubbles).toHaveLength(0);
    expect(getSnapshot().responseStarted).toBe(false);
  });

  it("opens the bubble only on the first non-empty token", () => {
    dispatchEvent({ kind: "llm_text_chunk", text: "", final: false });
    expect(getSnapshot().bubbles).toHaveLength(0);
    dispatchEvent({ kind: "llm_text_chunk", text: "Hi", final: false });
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
    dispatchEvent({ kind: "llm_text_chunk", text: "Hi", final: false });
    expect(getSnapshot().status).toBe("speaking");
    dispatchEvent({ kind: "llm_text_chunk", text: "", final: true });
    expect(getSnapshot().status).toBe("listening");
    dispatchEvent({ kind: "status", state: "listening" });
    expect(getSnapshot().status).toBe("listening");
  });
});
