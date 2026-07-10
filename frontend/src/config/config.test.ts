import { describe, expect, it } from "vitest";
import { _internal } from "./index";

/**
 * FE-1 acceptance: config values resolve from location-derived defaults, and an
 * https page derives wss:// / https:// (plan §3 edge cases).
 *
 * We test the derivation helpers directly since `config` is frozen at import.
 */

describe("config default derivation", () => {
  const origWindow = globalThis.window;

  function setLocation(protocol: string, hostname: string) {
    // @ts-expect-error minimal window stub for the derivation helpers
    globalThis.window = { location: { protocol, hostname } };
  }

  function restore() {
    globalThis.window = origWindow;
  }

  it("derives ws:// on an http page", () => {
    setLocation("http:", "192.168.1.50");
    expect(_internal.isSecurePage()).toBe(false);
    expect(_internal.defaultWsUrl()).toBe("ws://192.168.1.50:8765/ws");
    expect(_internal.defaultHealthUrl()).toBe("http://192.168.1.50:8000/health");
    restore();
  });

  it("derives wss:// / https:// on an https page", () => {
    setLocation("https:", "kiosk.example.com");
    expect(_internal.isSecurePage()).toBe(true);
    expect(_internal.defaultWsUrl()).toBe("wss://kiosk.example.com:8765/ws");
    expect(_internal.defaultHealthUrl()).toBe("https://kiosk.example.com:8000/health");
    restore();
  });

  it("falls back to localhost when window is absent", () => {
    // @ts-expect-error simulate non-browser
    globalThis.window = undefined;
    expect(_internal.currentHost()).toBe("localhost");
    expect(_internal.defaultWsUrl()).toBe("ws://localhost:8765/ws");
    restore();
  });
});
