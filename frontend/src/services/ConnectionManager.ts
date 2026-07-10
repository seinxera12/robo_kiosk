/**
 * ConnectionManager (FE-3).
 *
 * Owns the single WebSocket (REF §3.0). Responsibilities:
 *  - binaryType="arraybuffer" so binary frames arrive as ArrayBuffer (REF §3.8).
 *  - On open: send session_start, await session_ack before marking `ready`
 *    (REF §3.2). Input stays disabled until then.
 *  - Exponential backoff reconnect 1s -> 30s cap (REF §3.8). Every reopen
 *    re-sends session_start because reconnect = fresh server session (REF §3.8, §7).
 *  - Route inbound: JSON events to a handler, binary frames to the audio sink.
 *  - Never send app messages before `ready`.
 *
 * WS close 1011 (unhandled server error, REF §3.7) is treated like any drop:
 * reconnect with backoff.
 */
import { actions } from "../store/store";
import { appendTrace } from "../store/systemTraceStore";
import {
  decodeInbound,
  encodeSessionStart,
  type InboundEvent,
} from "./messages";

export interface ConnectionManagerOptions {
  url: string;
  kioskId: string;
  kioskLocation: string;
  /** Called for every decoded JSON event (not audio). */
  onEvent: (ev: InboundEvent) => void;
  /** Called for every binary audio frame (FE-6). */
  onAudio: (data: ArrayBuffer) => void;
  /** Backoff bounds (ms). Defaults match desktop (REF §3.8). */
  minBackoffMs?: number;
  maxBackoffMs?: number;
}

export class ConnectionManager {
  private ws: WebSocket | null = null;
  private readonly opts: Required<ConnectionManagerOptions>;
  private backoffMs: number;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private closedByUs = false;
  private acked = false;

  constructor(opts: ConnectionManagerOptions) {
    this.opts = {
      minBackoffMs: 1000,
      maxBackoffMs: 30000,
      ...opts,
    };
    this.backoffMs = this.opts.minBackoffMs;
  }

  /** Open the connection (idempotent-ish: no-op if already open/connecting). */
  connect(): void {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }
    this.closedByUs = false;
    this.acked = false;
    actions.setConnection(this.reconnectTimer ? "reconnecting" : "connecting");
    this.openSocket();
  }

  private openSocket(): void {
    let ws: WebSocket;
    try {
      ws = new WebSocket(this.opts.url);
    } catch {
      this.scheduleReconnect();
      return;
    }
    ws.binaryType = "arraybuffer";
    this.ws = ws;

    ws.onopen = () => {
      // Reconnect => fresh server session: re-send session_start (REF §3.8, §7).
      appendTrace("done", "socket connected");
      actions.setConnection("connected");
      this.send(encodeSessionStart(this.opts.kioskId, this.opts.kioskLocation), true);
    };

    ws.onmessage = (evt: MessageEvent) => {
      const decoded = decodeInbound(evt.data);
      if (decoded.kind === "audio") {
        this.opts.onAudio(decoded.data);
        return;
      }
      if (decoded.kind === "session_ack") {
        this.acked = true;
        this.backoffMs = this.opts.minBackoffMs; // healthy connection resets backoff
        actions.setConnection("ready");
        actions.setStatus("listening");
      }
      this.opts.onEvent(decoded);
    };

    ws.onerror = () => {
      // onerror is always followed by onclose; handle reconnect there.
    };

    ws.onclose = () => {
      this.ws = null;
      this.acked = false;
      if (this.closedByUs) {
        appendTrace("done", "socket closed");
        actions.setConnection("disconnected");
        return;
      }
      appendTrace("error", "socket dropped, reconnecting...");
      this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    actions.setConnection("reconnecting");
    if (this.reconnectTimer) return;
    const delay = this.backoffMs;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.openSocket();
    }, delay);
    // Exponential backoff toward the cap (REF §3.8).
    this.backoffMs = Math.min(this.backoffMs * 2, this.opts.maxBackoffMs);
  }

  /** True once session_ack has been received (input gate). */
  isReady(): boolean {
    return this.acked && this.ws?.readyState === WebSocket.OPEN;
  }

  /**
   * Send a text frame. App messages are refused before `ready`; the internal
   * session_start uses allowUnacked=true (REF §3.2: don't send app msgs early).
   */
  send(text: string, allowUnacked = false): boolean {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return false;
    if (!allowUnacked && !this.acked) return false;
    try {
      this.ws.send(text);
      return true;
    } catch {
      // Send failure -> drop + reconnect (REF §3.8).
      this.forceReconnect();
      return false;
    }
  }

  /** Send a binary frame (one whole utterance — REF §3.3.4). */
  sendBinary(data: ArrayBuffer): boolean {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN || !this.acked) return false;
    try {
      this.ws.send(data);
      return true;
    } catch {
      this.forceReconnect();
      return false;
    }
  }

  private forceReconnect(): void {
    try {
      this.ws?.close();
    } catch {
      /* ignore */
    }
    this.ws = null;
    this.acked = false;
    this.scheduleReconnect();
  }

  /**
   * Drop and reopen the socket (FE-14 clear-conversation: reconnect = fresh
   * server session with empty history, REF §3.8, §7).
   */
  reconnectNow(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.backoffMs = this.opts.minBackoffMs;
    try {
      this.closedByUs = true;
      this.ws?.close();
    } catch {
      /* ignore */
    }
    this.ws = null;
    this.acked = false;
    // Reopen immediately.
    this.connect();
  }

  /** Permanently close (component unmount). */
  dispose(): void {
    this.closedByUs = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    try {
      this.ws?.close();
    } catch {
      /* ignore */
    }
    this.ws = null;
  }
}
