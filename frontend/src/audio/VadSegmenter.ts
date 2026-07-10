/**
 * VadSegmenter (FE-8).
 *
 * Turns the continuous mic frame stream into discrete utterances, each sent as
 * ONE binary frame (REF §3.3.4, §3.9.1). Two modes:
 *   - manualSpeak (push-to-talk): buffer between start()/stop(); the guaranteed
 *     path. 15 s auto-flush timeout (REF §5.2).
 *   - alwaysListen (VAD): lightweight energy/RMS detector that runs entirely on
 *     the existing AudioCapture frame stream — no WASM, no external packages.
 *     A ~300 ms pre-roll avoids onset clipping (REF §5.2). Falls back to PTT
 *     if VAD cannot start (REF §5.2 edge case).
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

// Energy VAD tuning (REF §5.2). Browser AEC/NS is already on, so these
// thresholds can be kept low. Tune empirically for the deployment environment.
//
// SPEECH_THRESHOLD  – RMS above which a frame is considered "speech".
// SILENCE_THRESHOLD – RMS below which a frame is considered "silence"
//                     (hysteresis: lower than SPEECH to avoid choppy cuts).
// MIN_SPEECH_MS     – Minimum consecutive speech before we open the utterance.
// MIN_SILENCE_MS    – Minimum consecutive silence before we close it.
const SPEECH_THRESHOLD = 0.01; // ~-40 dBFS
const SILENCE_THRESHOLD = 0.006; // ~-44 dBFS  (hysteresis gap)
const MIN_SPEECH_MS = 200;
const MIN_SILENCE_MS = 800;

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

  // Energy VAD state
  private vadActive = false;
  private vadSpeechMs = 0;
  private vadSilenceMs = 0;
  private vadUnsubscribe: (() => void) | null = null;

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
   * Enable always-listen VAD using a lightweight RMS energy detector.
   * Runs entirely on the AudioCapture frame stream — no WASM, no external deps.
   * Returns immediately (synchronous setup wrapped in a Promise for API parity
   * with the old vad-web path so callers can still catch failures).
   */
  async startVad(): Promise<void> {
    if (this.vadActive) return;
    this.attach();
    this.vadActive = true;
    this.vadSpeechMs = 0;
    this.vadSilenceMs = 0;

    // Approximate milliseconds per worklet frame at the capture sample rate.
    const msPerFrame = (128 / this.capture.sampleRate) * 1000;

    this.vadUnsubscribe = this.capture.onFrame((frame) => {
      if (!this.vadActive) return;

      // Compute RMS of this frame.
      let sum = 0;
      for (let i = 0; i < frame.length; i++) sum += frame[i] * frame[i];
      const rms = Math.sqrt(sum / frame.length);

      if (!this.buffering) {
        // SILENCE state — waiting for speech onset.
        if (rms >= SPEECH_THRESHOLD) {
          this.vadSpeechMs += msPerFrame;
          if (this.vadSpeechMs >= MIN_SPEECH_MS) {
            // Confirmed speech start → open utterance with pre-roll.
            this.frames = [...this.prerollFrames];
            this.buffering = true;
            this.vadSilenceMs = 0;
          }
        } else {
          this.vadSpeechMs = 0;
        }
      } else {
        // SPEAKING state — waiting for end-of-speech silence.
        if (rms < SILENCE_THRESHOLD) {
          this.vadSilenceMs += msPerFrame;
          if (this.vadSilenceMs >= MIN_SILENCE_MS) {
            // Confirmed silence → close utterance and emit.
            this.buffering = false;
            this.vadSpeechMs = 0;
            this.emit();
          }
        } else {
          this.vadSilenceMs = 0;
        }
      }
    });
  }

  stopVad(): void {
    this.vadActive = false;
    this.vadUnsubscribe?.();
    this.vadUnsubscribe = null;
    if (this.buffering) {
      this.buffering = false;
      this.emit();
    }
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
    this.detach();
  }
}

export { MIN_UTTERANCE_BYTES, CAPTURE_SAMPLE_RATE };
