import { useEffect, useState } from "react";
import { config } from "../config";
import { fetchHealth, type HealthResult } from "../services/health";

/**
 * Health panel (FE-15). Polls /health every 10 s and renders service + TTS
 * status. A degraded TTS engine (e.g. kokoclone_ja: unavailable) is NOT treated
 * as failure — the endpoint is always 200 (REF §4.1). Collapsible to stay out
 * of the way of the kiosk UI.
 */
export function HealthPanel() {
  const [result, setResult] = useState<HealthResult | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    const poll = async () => {
      const r = await fetchHealth(config.healthUrl);
      if (alive) setResult(r);
    };
    void poll();
    const id = setInterval(poll, 10000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  const summary =
    result == null
      ? "…"
      : result.ok
      ? result.body.status ?? "unknown"
      : "unreachable";

  return (
    <div className={`health-panel ${open ? "open" : ""}`}>
      <button type="button" className="health-toggle" onClick={() => setOpen((v) => !v)}>
        Server: {summary}
      </button>
      {open && result?.ok && (
        <dl className="health-detail">
          {result.body.service && (
            <>
              <dt>Service</dt>
              <dd>
                {result.body.service} {result.body.version ?? ""}
              </dd>
            </>
          )}
          {result.body.tts &&
            Object.entries(result.body.tts).map(([engine, state]) => (
              <div key={engine} className="health-row">
                <dt>{engine}</dt>
                <dd className={state === "ready" ? "ok" : "warn"}>{state}</dd>
              </div>
            ))}
        </dl>
      )}
      {open && result && !result.ok && (
        <p className="health-detail warn">Health endpoint unreachable: {result.error}</p>
      )}
    </div>
  );
}
