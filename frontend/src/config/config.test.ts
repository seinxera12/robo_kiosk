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

/**
 * The packaged launcher serves the UI from http://127.0.0.1:<port>, so if the
 * funnel URL is ever missing from a production build the location fallback
 * silently aims the socket at the launcher's own file server. isLoopback is the
 * tripwire for that; it must not misfire on the real funnel host.
 */
describe("loopback detection (packaged-build tripwire)", () => {
  it("flags loopback WebSocket URLs", () => {
    expect(_internal.isLoopback("ws://127.0.0.1:5180/ws")).toBe(true);
    expect(_internal.isLoopback("ws://localhost:8765/ws")).toBe(true);
    expect(_internal.isLoopback("wss://localhost/ws")).toBe(true);
    expect(_internal.isLoopback("ws://[::1]:8765/ws")).toBe(true);
  });

  it("does not flag the funnel origin", () => {
    expect(_internal.isLoopback("wss://ubuntu.tailcd8da4.ts.net:8443/ws")).toBe(false);
  });

  it("does not flag hosts that merely start with the loopback name", () => {
    expect(_internal.isLoopback("wss://localhost.example.com:8443/ws")).toBe(false);
  });
});
