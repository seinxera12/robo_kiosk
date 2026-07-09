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

export interface VoiceControllerOptions {
  /** Send one complete utterance (SessionController.sendUtterance). */
  sendUtterance: (pcm: ArrayBuffer) => boolean;
}

export class VoiceController {
  private readonly capture = new AudioCapture();
  private readonly segmenter: VadSegmenter;
  private started = false;

  constructor(opts: VoiceControllerOptions) {
    this.segmenter = new VadSegmenter({
      capture: this.capture,
      onUtterance: (pcm) => opts.sendUtterance(pcm),
      onTooShort: () => {
        // Too-short clips are dropped silently (REF §3.3.4); keep listening.
      },
    });
  }

  private async ensureCapture(): Promise<boolean> {
    if (this.started) return true;
    try {
      await this.capture.start();
      this.started = true;
      return true;
    } catch {
      actions.setSoftError("Microphone access is required for voice.");
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
    } catch {
      // VAD unavailable -> fall back to PTT-only (REF §5.2 edge case).
      actions.setRecording("idle");
      actions.setSoftError("Auto-listen unavailable; use push-to-talk.");
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
