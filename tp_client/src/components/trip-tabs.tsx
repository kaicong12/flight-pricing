"use client";

// The three screens one trip has. Links rather than state, because each is its own route and each
// server-renders its own data — switching tabs must not carry the previous screen's props.
//
// A centered pill group in a full-bleed band, deliberately outside every page's `<main>`: the three
// routes have three different content widths, so anything aligned to the body moves when you switch.

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
    <div className="border-b border-border">
      <nav aria-label="This trip" className="flex h-13 items-center justify-center px-7">
        <div className="flex items-center gap-0.5 rounded-full border border-border bg-page p-0.5">
          {TABS.map(({ slug, label }) => {
            const href = `${base}${slug}`;
            const here = path === href;
            return (
              <Link
                key={label}
                href={href}
                aria-current={here ? "page" : undefined}
                className={cn(
                  "flex h-8 shrink-0 items-center rounded-full px-4 text-[13.5px] font-medium transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                  here
                    ? "surface text-ink shadow-card"
                    : "text-muted-foreground hover:text-ink",
                )}
              >
                {label}
              </Link>
            );
          })}
        </div>
      </nav>
    </div>
  );
}
