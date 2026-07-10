import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SessionController, type AudioSink } from "./SessionController";
import { _resetStore, getSnapshot } from "../store/store";

/** Reuse a minimal WebSocket mock (same shape as ConnectionManager.test). */
class MockWebSocket {
  static OPEN = 1;
  static CONNECTING = 0;
  static instances: MockWebSocket[] = [];
  readyState = 0;
  binaryType = "";
  sent: (string | ArrayBuffer)[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: unknown }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  constructor(public url: string) {
    MockWebSocket.instances.push(this);
  }
  send(d: string | ArrayBuffer) {
    this.sent.push(d);
  }
  close() {
    this.readyState = 3;
    this.onclose?.();
  }
  _open() {
    this.readyState = 1;
    this.onopen?.();
  }
  _msg(data: unknown) {
    this.onmessage?.({ data });
  }
}
const g = globalThis as unknown as { WebSocket: unknown };

describe("SessionController send paths (FE-5/9/10/11)", () => {
  let flushes: number;
  let audio: AudioSink;

  beforeEach(() => {
    MockWebSocket.instances = [];
    g.WebSocket = MockWebSocket;
    _resetStore();
    flushes = 0;
    audio = { push: () => {}, flush: () => (flushes += 1) };
  });
  afterEach(() => vi.restoreAllMocks());

  function ready(): { ctrl: SessionController; sock: MockWebSocket } {
    const ctrl = new SessionController({
      wsUrl: "ws://x/ws",
      kioskId: "k",
      kioskLocation: "loc",
      audio,
    });
    ctrl.start();
    const sock = MockWebSocket.instances[0];
    sock._open();
    sock._msg('{"type":"session_ack","status":"ready"}');
    return { ctrl, sock };
  }

  it("sendText echoes locally, sends lang:auto, flushes audio (REF §3.3.2)", () => {
    const { ctrl, sock } = ready();
    expect(ctrl.sendText("Where is the cafeteria?")).toBe(true);
    // local echo
    const { bubbles } = getSnapshot();
    expect(bubbles).toHaveLength(1);
    expect(bubbles[0].role).toBe("user");
    // sent frame (index 1; index 0 was session_start)
    const payload = JSON.parse(sock.sent[1] as string);
    expect(payload).toEqual({ type: "text_input", text: "Where is the cafeteria?", lang: "auto" });
    expect(flushes).toBe(1);
  });

  it("blocks empty text and text before ready", () => {
    const ctrl = new SessionController({ wsUrl: "ws://x/ws", kioskId: "k", kioskLocation: "l", audio });
    ctrl.start();
    expect(ctrl.sendText("hi")).toBe(false); // not ready
    const { ctrl: ready2 } = ready();
    expect(ready2.sendText("   ")).toBe(false); // empty
  });

  it("sendUtterance sends one binary frame + flushes (REF §3.3.4)", () => {
    const { ctrl, sock } = ready();
    const pcm = new ArrayBuffer(16000);
    expect(ctrl.sendUtterance(pcm)).toBe(true);
    const binaries = sock.sent.filter((s) => s instanceof ArrayBuffer);
    expect(binaries).toHaveLength(1);
    expect(flushes).toBe(1);
  });

  it("interrupt flushes audio and sends interrupt frame (REF §3.6)", () => {
    const { ctrl, sock } = ready();
    expect(ctrl.interrupt()).toBe(true);
    expect(JSON.parse(sock.sent[1] as string)).toEqual({ type: "interrupt" });
    expect(flushes).toBe(1);
  });

  it("clearConversation flushes, clears bubbles, reconnects (FE-14)", () => {
    const { ctrl } = ready();
    ctrl.sendText("hello");
    expect(getSnapshot().bubbles.length).toBeGreaterThan(0);
    ctrl.clearConversation();
    expect(getSnapshot().bubbles).toHaveLength(0);
    // a new socket was opened
    expect(MockWebSocket.instances.length).toBeGreaterThanOrEqual(2);
  });
});
