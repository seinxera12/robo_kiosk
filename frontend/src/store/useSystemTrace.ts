import { useSyncExternalStore } from "react";
import { getTraceSnapshot, subscribeTrace, type TraceLine } from "./systemTraceStore";

export function useSystemTrace(): TraceLine[] {
  return useSyncExternalStore(subscribeTrace, getTraceSnapshot);
}
