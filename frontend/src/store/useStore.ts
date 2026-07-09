import { useSyncExternalStore } from "react";
import { getSnapshot, subscribe, type AppState } from "./store";

/** Subscribe a component to the whole app state (plan §4.1). */
export function useStore(): AppState;
export function useStore<T>(selector: (s: AppState) => T): T;
export function useStore<T>(selector?: (s: AppState) => T): T | AppState {
  return useSyncExternalStore(subscribe, () =>
    selector ? selector(getSnapshot()) : getSnapshot()
  );
}
