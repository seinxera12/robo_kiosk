/**
 * Health polling (FE-15). GET /health is always 200; inspect the body, never
 * the status code (REF §4.1). CORS is * so the fetch is allowed (REF §3.1).
 * Partial bodies are tolerated (fields depend on init — REF §4.1).
 */

export interface HealthBody {
  status?: string;
  service?: string;
  version?: string;
  config?: Record<string, unknown>;
  tts?: Record<string, string>;
  [k: string]: unknown;
}

export type HealthResult =
  | { ok: true; body: HealthBody }
  | { ok: false; error: string };

export async function fetchHealth(url: string): Promise<HealthResult> {
  try {
    const res = await fetch(url, { method: "GET" });
    const body = (await res.json()) as HealthBody;
    return { ok: true, body };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "unreachable" };
  }
}
