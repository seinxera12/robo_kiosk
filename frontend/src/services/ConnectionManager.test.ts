import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ConnectionManager } from "./ConnectionManager";
import { _resetStore, getSnapshot } from "../store/store";
import type { InboundEvent } from "./messages";

/** Minimal WebSocket mock capturing sends and exposing lifecycle triggers. */
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
  // test helpers
  _open() {
    this.readyState = 1;
    this.onopen?.();
  }
  _msg(data: unknown) {
    this.onmessage?.({ data });
  }
}

const g = globalThis as unknown as { WebSocket: unknown };

describe("ConnectionManager (FE-3)", () => {
  let events: InboundEvent[];
  let audio: ArrayBuffer[];

  beforeEach(() => {
    vi.useFakeTimers();
    MockWebSocket.instances = [];
    g.WebSocket = MockWebSocket;
    _resetStore();
    events = [];
    audio = [];
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  function makeCm() {
    return new ConnectionManager({
      url: "ws://localhost:8765/ws",
      kioskId: "kiosk-01",
      kioskLocation: "Floor 1 Lobby",
      onEvent: (e) => events.push(e),
      onAudio: (a) => audio.push(a),
    });
  }

  it("sends session_start on open and becomes ready on ack", () => {
    const cm = makeCm();
    cm.connect();
    const sock = MockWebSocket.instances[0];
    expect(sock.binaryType).toBe("arraybuffer");

    sock._open();
    // session_start sent immediately, before ack
    expect(sock.sent).toHaveLength(1);
    expect(JSON.parse(sock.sent[0] as string).type).toBe("session_start");
    expect(cm.isReady()).toBe(false);
    expect(getSnapshot().connection).toBe("connected");

    sock._msg('{"type":"session_ack","status":"ready"}');
    expect(cm.isReady()).toBe(true);
    expect(getSnapshot().connection).toBe("ready");
  });

  it("refuses app messages before ack, allows after (REF §3.2)", () => {
    const cm = makeCm();
    cm.connect();
    const sock = MockWebSocket.instances[0];
    sock._open();
    expect(cm.send('{"type":"text_input"}')).toBe(false);
    sock._msg('{"type":"session_ack","status":"ready"}');
    expect(cm.send('{"type":"text_input"}')).toBe(true);
  });

  it("routes binary frames to the audio sink", () => {
    const cm = makeCm();
    cm.connect();
    const sock = MockWebSocket.instances[0];
    sock._open();
    sock._msg(new Uint8Array([1, 2, 3, 4]).buffer);
    expect(audio).toHaveLength(1);
  });

  it("reconnects with backoff and re-sends session_start (REF §3.8)", () => {
    const cm = makeCm();
    cm.connect();
    const first = MockWebSocket.instances[0];
    first._open();
    first._msg('{"type":"session_ack","status":"ready"}');

    // Server drops (e.g. close 1011).
    first.close();
    expect(getSnapshot().connection).toBe("reconnecting");

    // Advance past the 1s initial backoff.
    vi.advanceTimersByTime(1000);
    expect(MockWebSocket.instances).toHaveLength(2);
    const second = MockWebSocket.instances[1];
    second._open();
    expect(JSON.parse(second.sent[0] as string).type).toBe("session_start");
  });
});
