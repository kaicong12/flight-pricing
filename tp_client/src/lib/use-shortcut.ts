import { useEffect } from "react";

/** ⌘ or Ctrl plus `key`, ignored while any dialog is already open. */
export function useShortcut(key: string, run: () => void, enabled = true) {
  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.shiftKey || e.altKey) return;
      if (e.key.toLowerCase() !== key || document.querySelector('[role="dialog"]')) return;
      e.preventDefault();
      run();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [key, run, enabled]);
}
