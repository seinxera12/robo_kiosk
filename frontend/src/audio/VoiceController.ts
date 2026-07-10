/**
 * VoiceController (FE-9). Ties AudioCapture + VadSegmenter to the session's
 * sendUtterance, guaranteeing ONE binary frame per utterance (REF §3.3.4, #6 —
 * never per-frame, or the server self-interrupts). The transcript bubble comes
 * from the server `transcript` event (REF §3.4, #7), handled in the dispatcher.
 *
 * Modes mirror the desktop (REF §5.2, §8):
 *   - PTT: press -> startManual, release -> stopManual.
 *   - Always-listen: VAD auto-segments; falls back to PTT if VAD load fails.
 */
import { AudioCapture } from "./AudioCapture";
import { VadSegmenter } from "./VadSegmenter";
import { actions } from "../store/store";
import { appendTrace } from "../store/systemTraceStore";

export interface VoiceControllerOptions {
  /** Send one complete utterance (SessionController.sendUtterance). */
  sendUtterance: (pcm: ArrayBuffer) => boolean;
}

export type LevelListener = (level: number) => void;

function errMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export class VoiceController {
  private readonly capture = new AudioCapture();
  private readonly segmenter: VadSegmenter;
  private started = false;
  private readonly levelListeners = new Set<LevelListener>();

  constructor(opts: VoiceControllerOptions) {
    this.segmenter = new VadSegmenter({
      capture: this.capture,
      onUtterance: (pcm) => opts.sendUtterance(pcm),
      onTooShort: () => {
        // Too-short clips are dropped silently (REF §3.3.4); keep listening.
      },
    });
    // Local-only amplitude tap for the InputVisualizer (spec §3.2). Reuses the
    // existing capture frame stream — no separate AnalyserNode/audio graph,
    // and no backend event (there is no mic:level socket event).
    this.capture.onFrame((frame) => {
      if (this.levelListeners.size === 0) return;
      let sumSquares = 0;
      for (let i = 0; i < frame.length; i++) sumSquares += frame[i] * frame[i];
      const rms = Math.sqrt(sumSquares / frame.length);
      for (const l of this.levelListeners) l(rms);
    });
  }

  /** Subscribe to local mic amplitude (RMS, roughly 0-1). UI-only, not sent to the server. */
  onLevel(listener: LevelListener): () => void {
    this.levelListeners.add(listener);
    return () => this.levelListeners.delete(listener);
  }

  private async ensureCapture(): Promise<boolean> {
    if (this.started) return true;
    try {
      await this.capture.start();
      this.started = true;
      return true;
    } catch (err) {
      actions.setSoftError("Microphone access is required for voice.");
      appendTrace("error", `mic: access denied (${errMessage(err)})`);
      return false;
    }
  }

  // ------------------------------ PTT --------------------------------------

  async pressToTalk(): Promise<void> {
    if (!(await this.ensureCapture())) return;
    actions.setRecording("manualSpeak");
    this.segmenter.startManual();
  }

  releaseToTalk(): void {
    this.segmenter.stopManual();
    actions.setRecording("idle");
  }

  // -------------------------- Always-listen --------------------------------

  async enableAlwaysListen(): Promise<void> {
    if (!(await this.ensureCapture())) return;
    try {
      await this.segmenter.startVad();
      actions.setRecording("alwaysListen");
    } catch (err) {
      // VAD unavailable -> fall back to PTT-only (REF §5.2 edge case).
      actions.setRecording("idle");
      actions.setSoftError("Auto-listen unavailable; use push-to-talk.");
      appendTrace("error", `vad: failed to start (${errMessage(err)})`);
    }
  }

  disableAlwaysListen(): void {
    this.segmenter.stopVad();
    actions.setRecording("idle");
  }

  async dispose(): Promise<void> {
    this.segmenter.dispose();
    await this.capture.stop();
    this.started = false;
  }
}
