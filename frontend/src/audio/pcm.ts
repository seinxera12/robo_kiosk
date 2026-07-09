/**
 * PCM/WAV frame helpers (FE-6). Pure + unit-testable.
 *
 * The server sends 24 kHz mono PCM16 audio. Each logical unit is a complete WAV
 * file, BUT the server splits blobs >64 KB into ≤64 KB frames whose non-first
 * slices are headerless PCM (REF §5.3, #2). We therefore never rely on a full
 * container: if a frame starts with "RIFF" we strip the header; otherwise we
 * treat the whole frame as raw PCM16 (REF §5.3 recommendation).
 */

export const PLAYBACK_SAMPLE_RATE = 24000;

/** Canonical WAV header size for PCM (RIFF + fmt + data chunks). */
const CANONICAL_WAV_HEADER = 44;

function startsWithRiff(bytes: Uint8Array): boolean {
  return (
    bytes.length >= 4 &&
    bytes[0] === 0x52 && // R
    bytes[1] === 0x49 && // I
    bytes[2] === 0x46 && // F
    bytes[3] === 0x46 // F
  );
}

/**
 * Locate the PCM payload offset within a WAV frame by walking chunks to `data`.
 * Falls back to the canonical 44-byte header if parsing is inconclusive. This
 * tolerates engines that emit slightly non-canonical headers (OQ-2).
 */
function findDataOffset(view: DataView, bytes: Uint8Array): number {
  // "RIFF"____"WAVE" then a sequence of (id[4], size[4], payload[size]).
  if (bytes.length < 12) return CANONICAL_WAV_HEADER;
  // bytes 8..12 should be "WAVE"
  let offset = 12;
  while (offset + 8 <= bytes.length) {
    const id = String.fromCharCode(
      bytes[offset],
      bytes[offset + 1],
      bytes[offset + 2],
      bytes[offset + 3]
    );
    const size = view.getUint32(offset + 4, true);
    if (id === "data") {
      return offset + 8;
    }
    // Advance past this chunk (chunks are word-aligned).
    offset += 8 + size + (size % 2);
  }
  return CANONICAL_WAV_HEADER;
}

/**
 * Extract raw PCM16 little-endian samples from one binary frame, stripping a
 * WAV header if present. Returns an Int16Array view over a fresh buffer.
 * Guards against odd byte length (drops a trailing stray byte).
 */
export function frameToInt16(frame: ArrayBuffer): Int16Array {
  const bytes = new Uint8Array(frame);
  let payloadStart = 0;

  if (startsWithRiff(bytes)) {
    const view = new DataView(frame);
    payloadStart = findDataOffset(view, bytes);
  }

  let payloadLen = bytes.length - payloadStart;
  if (payloadLen <= 0) return new Int16Array(0);
  // Int16 alignment guard (REF §5.3 edge case: odd-length buffer).
  if (payloadLen % 2 !== 0) payloadLen -= 1;

  // Copy so we own an aligned buffer (payloadStart may be unaligned).
  const out = new Int16Array(payloadLen / 2);
  const dv = new DataView(frame, payloadStart, payloadLen);
  for (let i = 0; i < out.length; i++) {
    out[i] = dv.getInt16(i * 2, true);
  }
  return out;
}

/** Convert Int16 samples to Float32 [-1, 1) for Web Audio. */
export function int16ToFloat32(samples: Int16Array): Float32Array {
  const out = new Float32Array(samples.length);
  for (let i = 0; i < samples.length; i++) {
    out[i] = samples[i] / 32768;
  }
  return out;
}
