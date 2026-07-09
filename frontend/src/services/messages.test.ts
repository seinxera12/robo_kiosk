import { describe, expect, it } from "vitest";
import {
  decodeInbound,
  encodeInterrupt,
  encodeSessionReset,
  encodeSessionStart,
  encodeTextInput,
  stripBoilerplate,
} from "./messages";

describe("outbound encoding (REF §3.3)", () => {
  it("session_start carries kiosk identity", () => {
    expect(JSON.parse(encodeSessionStart("kiosk-01", "Floor 1 Lobby"))).toEqual({
      type: "session_start",
      kiosk_id: "kiosk-01",
      kiosk_location: "Floor 1 Lobby",
    });
  });

  it("text_input defaults lang to auto (REF §3.3.2, #8)", () => {
    expect(JSON.parse(encodeTextInput("Where is the cafeteria?"))).toEqual({
      type: "text_input",
      text: "Where is the cafeteria?",
      lang: "auto",
    });
  });

  it("interrupt and session_reset are bare typed frames", () => {
    expect(JSON.parse(encodeInterrupt())).toEqual({ type: "interrupt" });
    expect(JSON.parse(encodeSessionReset())).toEqual({ type: "session_reset" });
  });
});

describe("inbound decoding (REF §3.4)", () => {
  it("decodes session_ack", () => {
    expect(decodeInbound('{"type":"session_ack","status":"ready"}')).toEqual({
      kind: "session_ack",
      status: "ready",
    });
  });

  it("decodes transcript", () => {
    expect(
      decodeInbound('{"type":"transcript","text":"カフェはどこですか","lang":"ja","final":true}')
    ).toEqual({
      kind: "transcript",
      text: "カフェはどこですか",
      lang: "ja",
      final: true,
    });
  });

  it("preserves llm_text_chunk whitespace verbatim (REF §3.4)", () => {
    const ev = decodeInbound('{"type":"llm_text_chunk","text":"The cafeteria ","final":false}');
    expect(ev).toEqual({ kind: "llm_text_chunk", text: "The cafeteria ", final: false });
  });

  it("decodes the empty final chunk", () => {
    expect(decodeInbound('{"type":"llm_text_chunk","text":"","final":true}')).toEqual({
      kind: "llm_text_chunk",
      text: "",
      final: true,
    });
  });

  it("decodes status", () => {
    expect(decodeInbound('{"type":"status","state":"listening"}')).toEqual({
      kind: "status",
      state: "listening",
    });
  });

  it("maps unknown type to a benign variant (REF §4.2)", () => {
    const ev = decodeInbound('{"type":"audio_end"}');
    expect(ev.kind).toBe("unknown");
  });

  it("maps malformed JSON to malformed", () => {
    expect(decodeInbound("{not json").kind).toBe("malformed");
  });

  it("treats ArrayBuffer frames as audio", () => {
    const buf = new Uint8Array([1, 2, 3, 4]).buffer;
    const ev = decodeInbound(buf);
    expect(ev.kind).toBe("audio");
    if (ev.kind === "audio") expect(ev.data.byteLength).toBe(4);
  });
});

describe("boilerplate stripping (REF §3.5, #15)", () => {
  it("removes leaked language tags", () => {
    expect(stripBoilerplate("[Reply in English]Hello")).toBe("Hello");
    expect(stripBoilerplate("[日本語で回答してください]こんにちは")).toBe("こんにちは");
  });

  it("leaves clean text untouched, including trailing space", () => {
    expect(stripBoilerplate("The cafeteria ")).toBe("The cafeteria ");
  });
});
