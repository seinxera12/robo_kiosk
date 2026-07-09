import { describe, expect, it } from "vitest";
import {
  buildUtterancePcm,
  float32ToInt16,
  resampleLinear,
} from "./resample";

describe("resampleLinear (FE-7, REF §3.9.2)", () => {
  it("maps 1s at 48kHz to ~16000 samples", () => {
    const oneSec = new Float32Array(48000);
    const out = resampleLinear(oneSec, 48000, 16000);
    expect(out.length).toBe(16000);
  });

  it("preserves tone frequency (no pitch shift)", () => {
    // 1 kHz sine at 48 kHz for 0.1 s.
    const inRate = 48000;
    const durS = 0.1;
    const freq = 1000;
    const n = inRate * durS;
    const input = new Float32Array(n);
    for (let i = 0; i < n; i++) input[i] = Math.sin((2 * Math.PI * freq * i) / inRate);

    const out = resampleLinear(input, inRate, 16000);
    // Count zero-crossings; a 1 kHz tone over 0.1 s has ~200 crossings
    // regardless of sample rate (frequency preserved).
    let crossings = 0;
    for (let i = 1; i < out.length; i++) {
      if (Math.sign(out[i]) !== Math.sign(out[i - 1])) crossings++;
    }
    // ~2 crossings per cycle * 100 cycles = ~200 (allow tolerance).
    expect(crossings).toBeGreaterThan(180);
    expect(crossings).toBeLessThan(220);
  });

  it("is identity when rates match", () => {
    const x = new Float32Array([0.1, -0.2, 0.3]);
    const out = Array.from(resampleLinear(x, 16000, 16000));
    expect(out[0]).toBeCloseTo(0.1);
    expect(out[1]).toBeCloseTo(-0.2);
    expect(out[2]).toBeCloseTo(0.3);
  });
});

describe("float32ToInt16", () => {
  it("clamps out-of-range samples (REF §5.1)", () => {
    const out = float32ToInt16(new Float32Array([2.0, -2.0, 0, 1, -1]));
    expect(out[0]).toBe(32767);
    expect(out[1]).toBe(-32767);
    expect(out[2]).toBe(0);
  });
});

describe("buildUtterancePcm (FE-7)", () => {
  it("produces headerless little-endian Int16 bytes at 16kHz", () => {
    // 0.5 s at 48 kHz -> 8000 samples @16k -> 16000 bytes (the server minimum).
    const frame = new Float32Array(24000).fill(0.5);
    const buf = buildUtterancePcm([frame], 48000);
    expect(buf.byteLength).toBe(16000);
    // No RIFF header.
    const u8 = new Uint8Array(buf);
    expect(String.fromCharCode(u8[0], u8[1], u8[2], u8[3])).not.toBe("RIFF");
  });
});
