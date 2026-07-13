import { useEffect, useState } from "react";
import { config } from "../config";
import {
  componentsReady,
  fetchHealth,
  pendingComponents,
  type HealthBody,
} from "./health";

/**
 * Health gate (FE-15, deployment brief §1/§5).
 *
 * The server answers `healthy` before its models have finished loading, and the
 * first connection after a deploy can be slow for exactly that reason. This
 * hook polls /health and reports whether the pipeline is actually able to serve
 * a turn, so the UI can hold the mic back instead of dropping the user's first
 * utterance into a half-initialised STT.
 *
 * Poll cadence is asymmetric on purpose: fast while warming (so the kiosk arms
 * promptly once the models land) and slow once ready (it is only a liveness
 * check at that point).
 */

const WARMING_POLL_MS = 2000;
const READY_POLL_MS = 10000;

export type HealthPhase =
  /** No successful response yet — server unreachable or first poll in flight. */
  | "unreachable"
  /** Responding, but one or more required components are still loading. */
  | "warming"
  /** All required components ready — safe to enable the mic. */
  | "ready";

export interface HealthGate {
  phase: HealthPhase;
  /** Required components not yet ready (empty when phase === "ready"). */
  pending: string[];
  /** Last successful body, for detail display. */
  body: HealthBody | null;
  /** Error from the last failed poll, if any. */
  error: string | null;
}

export function useHealthGate(): HealthGate {
  const [gate, setGate] = useState<HealthGate>({
    phase: "unreachable",
    pending: [],
    body: null,
    error: null,
  });

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const poll = async () => {
      const result = await fetchHealth(config.healthUrl);
      if (!alive) return;

      let nextPhase: HealthPhase;
      if (!result.ok) {
        setGate({
          phase: "unreachable",
          pending: [],
          body: null,
          error: result.error,
        });
        nextPhase = "unreachable";
      } else {
        const ready = componentsReady(result.body);
        nextPhase = ready ? "ready" : "warming";
        setGate({
          phase: nextPhase,
          pending: ready ? [] : pendingComponents(result.body),
          body: result.body,
          error: null,
        });
      }

      // Re-arm. A plain setInterval would stack requests if a poll outlives its
      // period (likely on a cold, still-loading server), so chain instead.
      if (!alive) return;
      timer = setTimeout(
        poll,
        nextPhase === "ready" ? READY_POLL_MS : WARMING_POLL_MS
      );
    };

    void poll();

    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, []);

  return gate;
}
