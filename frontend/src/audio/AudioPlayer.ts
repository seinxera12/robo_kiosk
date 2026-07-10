/**
 * AudioPlayer (FE-6). Plays the inbound binary stream as 24 kHz mono PCM16 fed
 * to a Web Audio ring buffer — NOT decodeAudioData per frame, which would fail
 * on headerless >64 KB slices (REF §5.3, #2).
 *
 * Implements AudioSink (push/flush) so SessionController can drive it.
 *
 * Design:
 *  - AudioContext created at 24 kHz so the ring buffer plays 1:1 (REF §5.3).
 *  - Each frame -> frameToInt16 (strip RIFF if present) -> Float32 -> worklet.
 *  - flush() clears the worklet buffer instantly for barge-in (REF §5.4).
 *  - The context is resumed lazily on first push (autoplay policy needs a prior
 *    user gesture; the app has a mic/record button that provides one).
 *
 * onDrained is invoked when playback has emptied — used by FE-12 to help infer
 * end-of-turn audio.
 */
import { PLAYBACK_SAMPLE_RATE, frameToInt16, int16ToFloat32 } from "./pcm";
import type { AudioSink } from "../services/SessionController";

// Vite bundles the worklet as a separate module; import.meta.url resolves it to
// a real asset URL usable by audioWorklet.addModule().
const workletUrl = new URL("./playback-worklet.ts", import.meta.url).href;

export class AudioPlayer implements AudioSink {
  private ctx: AudioContext | null = null;
  private node: AudioWorkletNode | null = null;
  private gainNode: GainNode | null = null;
  private ready: Promise<void> | null = null;
  private pending: Float32Array[] = [];
  private disposed = false;
  private muted = false;
  private volume = 1;

  onDrained: (() => void) | null = null;

  private ensureContext(): Promise<void> {
    if (this.ready) return this.ready;
    this.ready = (async () => {
      const ctx = new AudioContext({ sampleRate: PLAYBACK_SAMPLE_RATE });
      await ctx.audioWorklet.addModule(workletUrl);
      const node = new AudioWorkletNode(ctx, "pcm-ring", {
        numberOfInputs: 0,
        numberOfOutputs: 1,
        outputChannelCount: [1],
      });
      node.port.onmessage = (e: MessageEvent) => {
        if (e.data?.type === "drained") this.onDrained?.();
      };
      const gainNode = ctx.createGain();
      gainNode.gain.value = this.muted ? 0 : this.volume;
      node.connect(gainNode);
      gainNode.connect(ctx.destination);
      this.ctx = ctx;
      this.node = node;
      this.gainNode = gainNode;
      // Flush any samples that arrived before the graph was ready.
      for (const s of this.pending) node.port.postMessage({ type: "push", samples: s }, [s.buffer]);
      this.pending = [];
    })();
    return this.ready;
  }

  /** Feed one binary WS frame for playback. */
  push(data: ArrayBuffer): void {
    if (this.disposed) return;
    const samples = int16ToFloat32(frameToInt16(data));
    if (samples.length === 0) return;

    if (this.node && this.ctx) {
      if (this.ctx.state === "suspended") void this.ctx.resume();
      this.node.port.postMessage({ type: "push", samples }, [samples.buffer]);
    } else {
      this.pending.push(samples);
      void this.ensureContext();
    }
  }

  /** Drop all queued audio and silence output immediately (barge-in, REF §5.4). */
  flush(): void {
    this.pending = [];
    this.node?.port.postMessage({ type: "flush" });
  }

  /** Mute/unmute TTS output (Composer volume toggle). Does not affect queued audio. */
  setMuted(muted: boolean): void {
    this.muted = muted;
    if (this.gainNode) this.gainNode.gain.value = muted ? 0 : this.volume;
  }

  /** Set TTS output volume, 0-1 (Composer volume control). */
  setVolume(volume: number): void {
    this.volume = Math.min(1, Math.max(0, volume));
    if (this.gainNode && !this.muted) this.gainNode.gain.value = this.volume;
  }

  dispose(): void {
    this.disposed = true;
    this.flush();
    try {
      this.node?.disconnect();
      this.gainNode?.disconnect();
    } catch {
      /* ignore */
    }
    void this.ctx?.close().catch(() => {});
    this.ctx = null;
    this.node = null;
    this.gainNode = null;
  }
}
