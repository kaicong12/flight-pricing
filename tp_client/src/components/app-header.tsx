"use client";

// The app bar: brand mark and the two-item nav. A trip is the only container, so there is no
// second level.

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

const NAV = [
  { href: "/trips", label: "Trips" },
  { href: "/", label: "New trip" },
];

export function AppHeader() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-30 flex h-15 items-center justify-between gap-6 border-b border-border bg-white/85 px-7 backdrop-blur-md">
      <div className="flex items-center gap-7">
        <Link href="/trips" className="flex shrink-0 items-center gap-2.5 rounded-full outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
          <span className="size-5.5 rounded-[999px_4px_999px_4px] bg-linear-135 from-ok to-brand" />
          <span className="text-[15px] font-semibold tracking-[-0.01em]">Trip Planner</span>
        </Link>
        <nav className="flex items-center gap-1">
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "rounded-full px-2.5 py-1.5 text-[13.5px] font-medium transition-colors hover:bg-page",
                "outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                pathname === item.href ? "text-ink" : "text-muted-foreground hover:text-ink",
              )}
            >
              {item.label}
            </Link>
          ))}
        </nav>
      </div>
      <div className="grid size-7 shrink-0 place-items-center rounded-full bg-[#d7cfba] text-[11px] font-semibold text-ink-soft">
        KC
      </div>
    </header>
  );
}
