import { useEffect, useSyncExternalStore } from "react";

const isMac = () => /Mac|iPhone|iPad/.test(navigator.userAgent);
const never = () => () => {};

export function useShortcut(key: string, run: () => void, enabled = true) {
  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent) => {
      if ((isMac() ? !e.metaKey : !e.ctrlKey) || e.shiftKey || e.altKey || e.isComposing) return;
      if (e.key.toLowerCase() !== key || document.querySelector('[role="dialog"]')) return;
      e.preventDefault();
      run();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [key, run, enabled]);
}

export function useModifierLabel(): string {
  return useSyncExternalStore(never, () => (isMac() ? "⌘" : "Ctrl "), () => "⌘");
}
