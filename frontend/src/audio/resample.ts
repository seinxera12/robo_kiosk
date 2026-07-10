/**
 * Resampling + format conversion for mic capture (FE-7). Pure + testable.
 *
 * Browsers capture at 44.1/48 kHz float; the server requires exactly 16 kHz
 * mono PCM16 little-endian (REF §3.3.4, §5.1, §3.9.2). Wrong rate silently
 * breaks STT (R-1), so this is covered by unit tests (tone / length checks).
 */

export const CAPTURE_SAMPLE_RATE = 16000;

/**
 * Linear-interpolation resample of a mono Float32 buffer from `inRate` to
 * `outRate`. Adequate for speech STT; higher-order filtering is unnecessary for
 * Whisper (REF §5.1 lists linear as acceptable).
 */
export function resampleLinear(
  input: Float32Array,
  inRate: number,
  outRate: number
): Float32Array {
  if (inRate === outRate) return input.slice();
  if (input.length === 0) return new Float32Array(0);

  const ratio = inRate / outRate;
  const outLen = Math.floor(input.length / ratio);
  const out = new Float32Array(outLen);
  for (let i = 0; i < outLen; i++) {
    const srcPos = i * ratio;
    const i0 = Math.floor(srcPos);
    const i1 = Math.min(i0 + 1, input.length - 1);
    const frac = srcPos - i0;
    out[i] = input[i0] * (1 - frac) + input[i1] * frac;
  }
  return out;
}

/** Convert Float32 [-1,1] to clamped Int16 PCM (REF §5.1: clamp*32767). */
export function float32ToInt16(input: Float32Array): Int16Array {
  const out = new Int16Array(input.length);
  for (let i = 0; i < input.length; i++) {
    const s = Math.max(-1, Math.min(1, input[i]));
    out[i] = Math.round(s * 32767);
  }
  return out;
}

/** Concatenate Float32 chunks into one buffer. */
export function concatFloat32(chunks: Float32Array[]): Float32Array {
  let total = 0;
  for (const c of chunks) total += c.length;
  const out = new Float32Array(total);
  let off = 0;
  for (const c of chunks) {
    out.set(c, off);
    off += c.length;
  }
  return out;
}

/**
 * Full mic-buffer pipeline: concat raw chunks (at inRate) -> resample to 16 kHz
 * -> Int16 -> raw little-endian bytes (no header — REF §3.3.4). Returns the
 * ArrayBuffer ready to send as one binary frame.
 */
export function buildUtterancePcm(
  chunks: Float32Array[],
  inRate: number
): ArrayBuffer {
  const mono = concatFloat32(chunks);
  const resampled = resampleLinear(mono, inRate, CAPTURE_SAMPLE_RATE);
  const int16 = float32ToInt16(resampled);
  // Copy into a fresh, definitely-non-shared ArrayBuffer (little-endian on all
  // supported platforms).
  const out = new ArrayBuffer(int16.byteLength);
  new Uint8Array(out).set(
    new Uint8Array(int16.buffer, int16.byteOffset, int16.byteLength)
  );
  return out;
}
