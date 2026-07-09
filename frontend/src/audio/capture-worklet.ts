/**
 * Capture AudioWorklet (FE-7). Forwards raw mono Float32 frames (at the context
 * sample rate, typically 48 kHz) to the main thread, which buffers + resamples
 * to 16 kHz (see resample.ts). Kept dumb on purpose so resampling logic stays
 * on the main thread where it is unit-tested.
 */

/// <reference lib="webworker" />

class CaptureProcessor extends AudioWorkletProcessor {
  process(inputs: Float32Array[][]): boolean {
    const channel = inputs[0]?.[0];
    if (channel && channel.length > 0) {
      // Copy — the render buffer is reused by the engine.
      this.port.postMessage(channel.slice(0));
    }
    return true;
  }
}

registerProcessor("pcm-capture", CaptureProcessor);
