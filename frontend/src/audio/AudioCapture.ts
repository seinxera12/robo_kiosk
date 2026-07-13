/**
 * AudioCapture (FE-7). getUserMedia -> AudioWorklet -> mono Float32 frames.
 *
 * Emits raw frames (at the context sample rate) to a listener so the VAD/PTT
 * segmenter (FE-8) can buffer them; on request it builds a 16 kHz mono PCM16
 * utterance (REF §3.3.4, §5.1). This class does NOT decide when to send — that
 * is the segmenter's job.
 *
 * Permission denial surfaces via the start() rejection (REF §5.1 edge case).
 */
import { buildUtterancePcm } from "./resample";
import { CAPTURE_WORKLET_URL } from "./workletUrl";

export type FrameListener = (frame: Float32Array, sampleRate: number) => void;

export class AudioCapture {
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private node: AudioWorkletNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private listeners = new Set<FrameListener>();
  private _sampleRate = 48000;

  get sampleRate(): number {
    return this._sampleRate;
  }

  get active(): boolean {
    return this.node !== null;
  }

  onFrame(listener: FrameListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /** Acquire mic + start streaming frames. Rejects on permission denial. */
  async start(): Promise<void> {
    if (this.node) return;
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
    const ctx = new AudioContext();
    await ctx.audioWorklet.addModule(CAPTURE_WORKLET_URL);
    this._sampleRate = ctx.sampleRate;

    const source = ctx.createMediaStreamSource(this.stream);
    const node = new AudioWorkletNode(ctx, "pcm-capture", {
      numberOfInputs: 1,
      numberOfOutputs: 0,
    });
    node.port.onmessage = (e: MessageEvent) => {
      const frame = e.data as Float32Array;
      for (const l of this.listeners) l(frame, this._sampleRate);
    };
    source.connect(node);

    this.ctx = ctx;
    this.source = source;
    this.node = node;
  }

  /** Stop streaming and release the mic. */
  async stop(): Promise<void> {
    try {
      this.source?.disconnect();
      this.node?.disconnect();
    } catch {
      /* ignore */
    }
    this.stream?.getTracks().forEach((t) => t.stop());
    await this.ctx?.close().catch(() => {});
    this.ctx = null;
    this.stream = null;
    this.node = null;
    this.source = null;
  }

  /**
   * Build a 16 kHz mono PCM16 utterance ArrayBuffer from buffered raw frames
   * (REF §3.3.4). The caller (segmenter) owns the frame buffer.
   */
  buildUtterance(frames: Float32Array[]): ArrayBuffer {
    return buildUtterancePcm(frames, this._sampleRate);
  }
}
