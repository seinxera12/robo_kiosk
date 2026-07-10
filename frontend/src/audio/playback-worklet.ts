/**
 * Playback AudioWorklet (FE-6). A Float32 ring buffer that outputs gaplessly at
 * the context sample rate (24 kHz — REF §5.3). Supports instant flush for
 * barge-in (REF §5.4): clearing the buffer silences output within one render
 * quantum (~2.7 ms at 24 kHz / 128 frames).
 *
 * Messages from main thread:
 *   {type:"push", samples: Float32Array}  – enqueue samples
 *   {type:"flush"}                        – drop everything, go silent
 * Messages to main thread:
 *   {type:"drained"}                      – buffer emptied after having data
 */

/// <reference lib="webworker" />

class RingBufferProcessor extends AudioWorkletProcessor {
  private queue: Float32Array[] = [];
  private readOffset = 0;
  private hadData = false;

  constructor() {
    super();
    this.port.onmessage = (e: MessageEvent) => {
      const msg = e.data;
      if (msg?.type === "push" && msg.samples) {
        this.queue.push(msg.samples as Float32Array);
        this.hadData = true;
      } else if (msg?.type === "flush") {
        this.queue = [];
        this.readOffset = 0;
      }
    };
  }

  process(_inputs: Float32Array[][], outputs: Float32Array[][]): boolean {
    const channel = outputs[0][0];
    if (!channel) return true;

    for (let i = 0; i < channel.length; i++) {
      const chunk = this.queue[0];
      if (!chunk) {
        channel[i] = 0;
        if (this.hadData && this.queue.length === 0) {
          this.hadData = false;
          this.port.postMessage({ type: "drained" });
        }
        continue;
      }
      channel[i] = chunk[this.readOffset++];
      if (this.readOffset >= chunk.length) {
        this.queue.shift();
        this.readOffset = 0;
      }
    }
    return true; // keep processor alive
  }
}

registerProcessor("pcm-ring", RingBufferProcessor);
