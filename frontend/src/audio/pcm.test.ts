import { describe, expect, it } from "vitest";
import { frameToInt16, int16ToFloat32 } from "./pcm";

/** Build a minimal canonical 44-byte WAV header + PCM payload. */
function makeWav(samples: number[]): ArrayBuffer {
  const dataBytes = samples.length * 2;
  const buf = new ArrayBuffer(44 + dataBytes);
  const dv = new DataView(buf);
  const u8 = new Uint8Array(buf);
  const write = (off: number, s: string) => {
    for (let i = 0; i < s.length; i++) u8[off + i] = s.charCodeAt(i);
  };
  write(0, "RIFF");
  dv.setUint32(4, 36 + dataBytes, true);
  write(8, "WAVE");
  write(12, "fmt ");
  dv.setUint32(16, 16, true);
  dv.setUint16(20, 1, true); // PCM
  dv.setUint16(22, 1, true); // mono
  dv.setUint32(24, 24000, true);
  dv.setUint32(28, 48000, true);
  dv.setUint16(32, 2, true);
  dv.setUint16(34, 16, true);
  write(36, "data");
  dv.setUint32(40, dataBytes, true);
  for (let i = 0; i < samples.length; i++) dv.setInt16(44 + i * 2, samples[i], true);
  return buf;
}

function rawPcm(samples: number[]): ArrayBuffer {
  const buf = new ArrayBuffer(samples.length * 2);
  const dv = new DataView(buf);
  for (let i = 0; i < samples.length; i++) dv.setInt16(i * 2, samples[i], true);
  return buf;
}

describe("frameToInt16 (FE-6, REF §5.3)", () => {
  it("strips a canonical RIFF header (first slice of a WAV)", () => {
    const wav = makeWav([100, -200, 300, 32767, -32768]);
    expect(Array.from(frameToInt16(wav))).toEqual([100, -200, 300, 32767, -32768]);
  });

  it("treats a headerless frame as raw PCM16 (non-first >64KB slice, #2)", () => {
    const raw = rawPcm([1, 2, 3, 4]);
    expect(Array.from(frameToInt16(raw))).toEqual([1, 2, 3, 4]);
  });

  it("guards odd-length raw buffers (drops stray trailing byte)", () => {
    const buf = new ArrayBuffer(5); // 2 full int16 + 1 stray
    const dv = new DataView(buf);
    dv.setInt16(0, 111, true);
    dv.setInt16(2, 222, true);
    expect(Array.from(frameToInt16(buf))).toEqual([111, 222]);
  });

  it("returns empty for an empty frame", () => {
    expect(frameToInt16(new ArrayBuffer(0)).length).toBe(0);
  });
});

describe("int16ToFloat32", () => {
  it("scales to [-1, 1)", () => {
    const f = int16ToFloat32(new Int16Array([0, 16384, -32768]));
    expect(f[0]).toBeCloseTo(0);
    expect(f[1]).toBeCloseTo(0.5);
    expect(f[2]).toBeCloseTo(-1);
  });
});
