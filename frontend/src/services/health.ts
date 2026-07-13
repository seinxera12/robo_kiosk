/**
 * Health polling (FE-15). GET /health is always 200; inspect the body, never
 * the status code (REF §4.1). CORS is * so the fetch is allowed (REF §3.1).
 * Partial bodies are tolerated (fields depend on init — REF §4.1).
 *
 * Readiness gate: the server pre-loads models at startup and will answer
 * `{"status":"healthy"}` while STT/LLM/RAG are STILL LOADING. `status` alone is
 * therefore not a readiness signal — the per-component states under `components`
 * are. The first connection after a deploy can sit in this warming state for a
 * while, so the UI polls until the components report ready before arming the mic.
 *
 * `tts` is deliberately NOT part of the gate: a degraded engine (e.g.
 * `kokoclone_ja: unavailable`) is a partial-capability condition, not a failure,
 * and must not brick the kiosk.
 */

/** Per-component readiness. Components appear as they finish initialising. */
export interface HealthComponents {
  stt?: string;
  llm_chain?: string;
  rag?: string;
  [k: string]: string | undefined;
}

export interface HealthBody {
  status?: string;
  service?: string;
  version?: string;
  config?: Record<string, unknown>;
  components?: HealthComponents;
  tts?: Record<string, string>;
  [k: string]: unknown;
}

export type HealthResult =
  | { ok: true; body: HealthBody }
  | { ok: false; error: string };

/** Components that must be ready before the pipeline can serve a turn. */
const REQUIRED_COMPONENTS = ["stt", "llm_chain", "rag"] as const;

/**
 * True when every required component reports ready.
 *
 * Conservative by design: a body with no `components` key is treated as NOT
 * ready. During startup the server omits components that haven't initialised,
 * so "absent" means "not up yet" — assuming ready there would re-introduce the
 * exact race this gate exists to prevent.
 */
export function componentsReady(body: HealthBody): boolean {
  const components = body.components;
  if (!components) return false;
  return REQUIRED_COMPONENTS.every((name) => components[name] === "ready");
}

/** Required components that are not yet reporting ready (for the UI label). */
export function pendingComponents(body: HealthBody): string[] {
  const components = body.components ?? {};
  return REQUIRED_COMPONENTS.filter((name) => components[name] !== "ready");
}

export async function fetchHealth(url: string): Promise<HealthResult> {
  try {
    const res = await fetch(url, { method: "GET" });
    const body = (await res.json()) as HealthBody;
    return { ok: true, body };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "unreachable" };
  }
}
