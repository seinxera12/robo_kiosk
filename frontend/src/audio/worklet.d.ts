/**
 * Ambient declarations for the AudioWorkletGlobalScope (not in lib.dom).
 * Used by playback-worklet.ts and capture-worklet.ts.
 */
declare class AudioWorkletProcessor {
  readonly port: MessagePort;
  constructor(options?: unknown);
  process(
    inputs: Float32Array[][],
    outputs: Float32Array[][],
    parameters: Record<string, Float32Array>
  ): boolean;
}

declare function registerProcessor(
  name: string,
  processorCtor: new (options?: unknown) => AudioWorkletProcessor
): void;

declare const sampleRate: number;
declare const currentTime: number;
