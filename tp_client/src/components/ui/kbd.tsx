"use client";

import { useModifierLabel } from "@/lib/use-shortcut";

export function Kbd({ letter }: { letter: string }) {
  return (
    <kbd className="rounded border border-border px-1 font-mono text-[10.5px] text-faint">
      {useModifierLabel()}
      {letter}
    </kbd>
  );
}
