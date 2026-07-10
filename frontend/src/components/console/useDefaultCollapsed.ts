import { useState } from "react";

const MOBILE_BREAKPOINT = "(max-width: 1024px)";

/**
 * Left/right panels default to collapsed accordions on narrow viewports so
 * the transcript stays primary (spec §7), but default to expanded on desktop
 * where they're always-visible side columns, not accordions.
 */
export function useDefaultCollapsed(): [boolean, (fn: (c: boolean) => boolean) => void] {
  const [collapsed, setCollapsed] = useState(
    () => typeof window !== "undefined" && window.matchMedia(MOBILE_BREAKPOINT).matches
  );
  return [collapsed, setCollapsed];
}
