/**
 * VadSegmenter (FE-8).
 *
 * Turns the continuous mic frame stream into discrete utterances, each sent as
 * ONE binary frame (REF §3.3.4, §3.9.1). Two modes:
 *   - manualSpeak (push-to-talk): buffer between start()/stop(); the guaranteed
 *     path. 15 s auto-flush timeout (REF §5.2).
 *   - alwaysListen (VAD): uses @ricky0123/vad-web (Silero) to detect end-of-
 *     speech; a ~300 ms pre-roll avoids onset clipping (REF §5.2). Falls back to
 *     PTT if VAD fails to load (REF §5.2 edge case).
 *
 * Enforces the >=0.5 s / >=16000-byte minimum: shorter utterances are dropped
 * client-side before sending (REF §3.3.4).
 *
 * This module owns frame buffering from AudioCapture and emits a ready PCM
 * ArrayBuffer via onUtterance. It does NOT touch the socket (FE-9 does).
 */
import { AudioCapture } from "./AudioCapture";
import { CAPTURE_SAMPLE_RATE } from "./resample";

const MIN_UTTERANCE_BYTES = 16000; // 0.5 s @ 16 kHz PCM16 (REF §3.3.4)
const PREROLL_MS = 300;
const MANUAL_SPEAK_TIMEOUT_MS = 15000; // REF §5.2

export type SegmenterMode = "manualSpeak" | "alwaysListen";

export interface VadSegmenterOptions {
  capture: AudioCapture;
  onUtterance: (pcm: ArrayBuffer) => void;
  /** Notified when an utterance was dropped for being too short. */
  onTooShort?: () => void;
}

export class VadSegmenter {
  private readonly capture: AudioCapture;
  private readonly onUtterance: (pcm: ArrayBuffer) => void;
  private readonly onTooShort?: () => void;

  private frames: Float32Array[] = [];
  private prerollFrames: Float32Array[] = [];
  private buffering = false;
  private unsubscribe: (() => void) | null = null;
  private manualTimeout: ReturnType<typeof setTimeout> | null = null;
  private vad: { start: () => void; pause: () => void; destroy: () => void } | null = null;

  constructor(opts: VadSegmenterOptions) {
    this.capture = opts.capture;
    this.onUtterance = opts.onUtterance;
    this.onTooShort = opts.onTooShort;
  }

  private prerollFrameCount(): number {
    const framesPerMs = this.capture.sampleRate / 1000 / 128; // ~worklet quantum
    return Math.max(1, Math.round(PREROLL_MS * framesPerMs));
  }

  /** Attach to the capture frame stream (keeps a rolling pre-roll buffer). */
  private attach(): void {
    if (this.unsubscribe) return;
    this.unsubscribe = this.capture.onFrame((frame) => {
      if (this.buffering) {
        this.frames.push(frame);
      } else {
        // Maintain a small rolling pre-roll.
        this.prerollFrames.push(frame);
        const max = this.prerollFrameCount();
        while (this.prerollFrames.length > max) this.prerollFrames.shift();
      }
    });
  }

  private detach(): void {
    this.unsubscribe?.();
    this.unsubscribe = null;
  }

  // ---------------------------- Push-to-talk -------------------------------

  /** Begin buffering an utterance (PTT press). Seeds with the pre-roll. */
  startManual(): void {
    this.attach();
    this.frames = [...this.prerollFrames];
    this.buffering = true;
    if (this.manualTimeout) clearTimeout(this.manualTimeout);
    this.manualTimeout = setTimeout(() => this.stopManual(), MANUAL_SPEAK_TIMEOUT_MS);
  }

  /** End buffering (PTT release / 15 s timeout) and emit if long enough. */
  stopManual(): void {
    if (this.manualTimeout) {
      clearTimeout(this.manualTimeout);
      this.manualTimeout = null;
    }
    if (!this.buffering) return;
    this.buffering = false;
    this.emit();
  }

  // ------------------------------- VAD -------------------------------------

  /**
   * Enable always-listen VAD. Dynamically imports vad-web; on failure the
   * caller should fall back to PTT (this rejects). We drive the buffer from our
   * own capture frames using VAD's speech start/end callbacks.
   */
  async startVad(): Promise<void> {
    // NOTE: MicVAD opens its own mic stream for detection; we use it purely for
    // speech start/end *timing* and still send audio from our own AudioCapture
    // buffer (which is guaranteed 16 kHz PCM16). Two streams are open in this
    // mode — acceptable since VAD is the convenience path; PTT is the guaranteed
    // one (REF §5.2, OQ-4). Tune thresholds empirically.
    this.attach();
    const mod = await import("@ricky0123/vad-web");
    const vad = await mod.MicVAD.new({
      // Desktop parity (REF §5.2, OQ-4); tune empirically.
      positiveSpeechThreshold: 0.3,
      minSpeechMs: 200, // desktop min-speech (REF §5.2)
      redemptionMs: 800, // ~800 ms min-silence (REF §5.2)
      onSpeechStart: () => {
        this.frames = [...this.prerollFrames];
        this.buffering = true;
      },
      onSpeechEnd: () => {
        this.buffering = false;
        this.emit();
      },
    });
    vad.start();
    this.vad = vad;
  }

  stopVad(): void {
    this.vad?.pause();
    this.buffering = false;
  }

  // ------------------------------ Shared -----------------------------------

  private emit(): void {
    const frames = this.frames;
    this.frames = [];
    if (frames.length === 0) return;
    const pcm = this.capture.buildUtterance(frames);
    // Enforce the >=0.5 s minimum before sending (REF §3.3.4).
    if (pcm.byteLength < MIN_UTTERANCE_BYTES) {
      this.onTooShort?.();
      return;
    }
    this.onUtterance(pcm);
  }

  dispose(): void {
    this.stopVad();
    if (this.manualTimeout) clearTimeout(this.manualTimeout);
    this.vad?.destroy();
    this.vad = null;
    this.detach();
  }
}

export { MIN_UTTERANCE_BYTES, CAPTURE_SAMPLE_RATE };
