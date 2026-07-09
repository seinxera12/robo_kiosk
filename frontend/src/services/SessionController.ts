/**
 * SessionController (FE-5 onward).
 *
 * Wires ConnectionManager <-> store <-> audio. Owns the app-level actions the
 * UI calls: sendText, (later) sendUtterance, interrupt, clearConversation.
 * Kept framework-free so it can be unit-tested and driven from React effects.
 *
 * Text send (FE-5): render the user's message LOCALLY (no transcript echo for
 * typed input — REF §3.3.2, #7), send text_input{lang:"auto"} (server
 * re-detects — REF §3.3.2, #8). Sending implicitly interrupts server-side, so
 * flush local audio too (REF §3.3.2; full wiring in FE-11).
 */
import { actions } from "../store/store";
import { getSnapshot } from "../store/store";
import { dispatchEvent, type DispatchHooks } from "../store/eventDispatch";
import { ConnectionManager } from "./ConnectionManager";
import {
  encodeInterrupt,
  encodeTextInput,
  type InboundEvent,
} from "./messages";

export interface AudioSink {
  /** Feed a binary frame for playback (FE-6). */
  push(data: ArrayBuffer): void;
  /** Drop queued audio + stop output immediately for barge-in (FE-6/§5.4). */
  flush(): void;
}

/** No-op audio sink used until the real AudioPlayer is wired (FE-6). */
export const nullAudioSink: AudioSink = { push: () => {}, flush: () => {} };

export interface SessionControllerOptions {
  wsUrl: string;
  kioskId: string;
  kioskLocation: string;
  audio?: AudioSink;
  hooks?: DispatchHooks;
}

export class SessionController {
  private readonly conn: ConnectionManager;
  private readonly audio: AudioSink;
  private readonly hooks: DispatchHooks;

  constructor(opts: SessionControllerOptions) {
    this.audio = opts.audio ?? nullAudioSink;
    this.hooks = opts.hooks ?? {};
    this.conn = new ConnectionManager({
      url: opts.wsUrl,
      kioskId: opts.kioskId,
      kioskLocation: opts.kioskLocation,
      onEvent: (ev) => this.onEvent(ev),
      onAudio: (data) => this.audio.push(data),
    });
  }

  start(): void {
    this.conn.connect();
  }

  dispose(): void {
    this.conn.dispose();
  }

  isReady(): boolean {
    return this.conn.isReady();
  }

  private onEvent(ev: InboundEvent): void {
    dispatchEvent(ev, this.hooks);
  }

  /**
   * FE-5: send a typed query. Renders the user bubble locally and sends
   * text_input{lang:"auto"}. Returns false if not ready or input was empty.
   */
  sendText(text: string): boolean {
    const trimmed = text.trim();
    if (trimmed.length === 0) return false;
    if (!this.conn.isReady()) return false;

    // Barge-in: sending preempts any in-progress response (REF §3.3.2).
    this.audio.flush();
    // Close any dangling assistant bubble locally so the next turn is clean.
    if (getSnapshot().responseStarted) actions.finishAssistantResponse();

    // Local echo — server does NOT echo typed input (REF §3.3.2, #7).
    actions.addUserBubble(trimmed);
    actions.setStatus("thinking");
    this.hooks.onSend?.();

    return this.conn.send(encodeTextInput(trimmed, "auto"));
  }

  /** FE-9: send one complete utterance as a single binary frame (REF §3.3.4). */
  sendUtterance(pcm: ArrayBuffer): boolean {
    if (!this.conn.isReady()) return false;
    // Voice barge-in: stop local playback; server auto-interrupts (REF §3.6).
    this.audio.flush();
    if (getSnapshot().responseStarted) actions.finishAssistantResponse();
    actions.setStatus("thinking");
    this.hooks.onSend?.();
    return this.conn.sendBinary(pcm);
  }

  /** FE-10: explicit barge-in. Flush local audio + tell the server. */
  interrupt(): boolean {
    this.audio.flush();
    return this.conn.send(encodeInterrupt());
  }

  /**
   * FE-14: clear conversation. Default path = reconnect (fresh server session,
   * REF §3.8, §7) since session_reset is a server no-op (REF #1).
   */
  clearConversation(): void {
    this.audio.flush();
    actions.clearBubbles();
    this.conn.reconnectNow();
  }
}
