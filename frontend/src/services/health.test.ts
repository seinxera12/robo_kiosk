import { describe, expect, it } from "vitest";
import { componentsReady, pendingComponents, type HealthBody } from "./health";

/**
 * The readiness gate exists because `status: "healthy"` is returned while the
 * server is still loading models. These tests pin the thing that makes the gate
 * worth having: `healthy` must never on its own be enough to arm the mic.
 */
describe("health readiness gate", () => {
  it("is ready only when every required component reports ready", () => {
    const body: HealthBody = {
      status: "healthy",
      components: { stt: "ready", llm_chain: "ready", rag: "ready" },
    };
    expect(componentsReady(body)).toBe(true);
    expect(pendingComponents(body)).toEqual([]);
  });

  it("is NOT ready when status is healthy but components are still loading", () => {
    const body: HealthBody = {
      status: "healthy",
      components: { stt: "loading", llm_chain: "ready", rag: "ready" },
    };
    expect(componentsReady(body)).toBe(false);
    expect(pendingComponents(body)).toEqual(["stt"]);
  });

  it("is NOT ready when the components key is absent entirely", () => {
    // Startup: the server omits components that have not initialised yet.
    // Treating absent as ready would reintroduce the race the gate prevents.
    expect(componentsReady({ status: "healthy" })).toBe(false);
    expect(pendingComponents({ status: "healthy" })).toEqual([
      "stt",
      "llm_chain",
      "rag",
    ]);
  });

  it("is NOT ready when a required component is missing from the map", () => {
    const body: HealthBody = {
      status: "healthy",
      components: { stt: "ready", llm_chain: "ready" }, // rag not up yet
    };
    expect(componentsReady(body)).toBe(false);
    expect(pendingComponents(body)).toEqual(["rag"]);
  });

  it("ignores TTS health — a degraded engine must not brick the kiosk", () => {
    const body: HealthBody = {
      status: "healthy",
      components: { stt: "ready", llm_chain: "ready", rag: "ready" },
      tts: { kokoro_en: "ready", kokoclone_ja: "unavailable" },
    };
    expect(componentsReady(body)).toBe(true);
  });
});
