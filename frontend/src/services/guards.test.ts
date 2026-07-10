import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TimeoutGuard } from "./TimeoutGuard";
import { PlaybackTracker } from "./PlaybackTracker";
import { _resetStore, actions, getSnapshot } from "../store/store";

describe("TimeoutGuard (FE-13, REF §3.7/#5)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    _resetStore();
  });
  afterEach(() => vi.useRealTimers());

  it("fires a soft error when no activity arrives", () => {
    const g = new TimeoutGuard(20000);
    actions.appendAssistantToken("partial"); // open a bubble
    g.arm();
    vi.advanceTimersByTime(20000);
    expect(getSnapshot().softError).toBeTruthy();
    expect(getSnapshot().status).toBe("listening");
    // dangling bubble closed
    expect(getSnapshot().bubbles.every((b) => !b.open)).toBe(true);
  });

  it("disarm cancels the timeout (normal streamed turn)", () => {
    const g = new TimeoutGuard(20000);
    g.arm();
    vi.advanceTimersByTime(5000);
    g.disarm();
    vi.advanceTimersByTime(20000);
    expect(getSnapshot().softError).toBeNull();
  });
});

describe("PlaybackTracker (FE-12, REF #4)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    _resetStore();
  });
  afterEach(() => vi.useRealTimers());

  function fakePlayer() {
    const p = { onDrained: null as null | (() => void) };
    return p as unknown as import("../audio/AudioPlayer").AudioPlayer & {
      onDrained: (() => void) | null;
    };
  }

  it("text-only turn completes immediately (no audio)", () => {
    const player = fakePlayer();
    const t = new PlaybackTracker(player);
    actions.setStatus("speaking");
    t.onTextFinal();
    expect(getSnapshot().status).toBe("listening");
  });

  it("waits for drain + idle window before clearing speaking", () => {
    const player = fakePlayer();
    const t = new PlaybackTracker(player);
    actions.setStatus("speaking");

    t.onAudioFrame(); // audio in flight
    t.onTextFinal(); // text done but audio not drained
    expect(getSnapshot().status).toBe("speaking");

    // Buffer drains.
    player.onDrained?.();
    // Still within idle window.
    vi.advanceTimersByTime(499);
    expect(getSnapshot().status).toBe("speaking");
    vi.advanceTimersByTime(2);
    expect(getSnapshot().status).toBe("listening");
  });
});
