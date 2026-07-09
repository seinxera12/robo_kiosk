/**
 * PlaybackTracker (FE-12).
 *
 * There is no end-of-audio signal (REF §3.5, #4). We infer a turn's audio is
 * complete when ALL hold:
 *   - text stream ended (llm_text_chunk final:true), AND
 *   - the audio ring buffer has drained, AND
 *   - no new binary frame arrived within a short idle window (OQ-5, ~500 ms).
 * Only then do we clear "speaking" -> "listening". Never clear while frames are
 * still queued (audio can lag text — REF #4). A text-only turn (no audio) also
 * completes: if no audio frame ever arrived, the text-final alone completes it.
 */
import { actions, getSnapshot } from "../store/store";
import type { AudioPlayer } from "../audio/AudioPlayer";

const IDLE_WINDOW_MS = 500; // OQ-5

export class PlaybackTracker {
  private textFinal = false;
  private sawAudio = false;
  private drained = true;
  private lastFrameAt = 0;
  private idleTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(player: AudioPlayer) {
    player.onDrained = () => {
      this.drained = true;
      this.maybeComplete();
    };
  }

  /** A binary audio frame arrived (turn is producing audio). */
  onAudioFrame(): void {
    this.sawAudio = true;
    this.drained = false;
    this.lastFrameAt = Date.now();
  }

  /** llm_text_chunk final:true received. */
  onTextFinal(): void {
    this.textFinal = true;
    if (!this.sawAudio) {
      // Text-only turn — complete immediately.
      this.complete();
      return;
    }
    this.maybeComplete();
  }

  private maybeComplete(): void {
    if (!this.textFinal || !this.drained) return;
    // Debounce against a late frame arriving within the idle window.
    if (this.idleTimer) clearTimeout(this.idleTimer);
    const sinceLast = Date.now() - this.lastFrameAt;
    const wait = Math.max(0, IDLE_WINDOW_MS - sinceLast);
    this.idleTimer = setTimeout(() => {
      this.idleTimer = null;
      if (this.textFinal && this.drained) this.complete();
    }, wait);
  }

  private complete(): void {
    this.reset();
    if (getSnapshot().status === "speaking") actions.setStatus("listening");
  }

  /** Reset per-turn tracking (called on new turn / barge-in flush). */
  reset(): void {
    this.textFinal = false;
    this.sawAudio = false;
    this.drained = true;
    if (this.idleTimer) {
      clearTimeout(this.idleTimer);
      this.idleTimer = null;
    }
  }

  dispose(): void {
    this.reset();
  }
}
