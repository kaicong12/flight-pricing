"use client";

// The three screens one trip has. Links rather than state, because each is its own route and each
// server-renders its own data — switching tabs must not carry the previous screen's props.

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

const TABS = [
  { slug: "", label: "Status" },
  { slug: "/plan", label: "Plan" },
  { slug: "/expenses", label: "Expenses" },
];

export function TripTabs({ tripId }: { tripId: string }) {
  const path = usePathname();
  const base = `/trip/${encodeURIComponent(tripId)}`;

  return (
    <nav
      aria-label="This trip"
      className="flex items-center gap-1 overflow-x-auto border-b border-border"
    >
      {TABS.map(({ slug, label }) => {
        const href = `${base}${slug}`;
        return (
          <Link
            key={label}
            href={href}
            aria-current={path === href ? "page" : undefined}
            className={cn(
              "-mb-px flex h-10 shrink-0 items-center border-b-2 px-3 text-[13.5px] font-medium transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
              path === href
                ? "border-ink text-ink"
                : "border-transparent text-muted-foreground hover:text-ink",
            )}
          >
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
