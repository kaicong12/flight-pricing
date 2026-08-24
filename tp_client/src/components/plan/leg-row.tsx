// The travel between two blocks. Machine output, so mono throughout.

import type { PlanLeg, TravelMode } from "@/lib/plan-types";
import { formatDistance, formatMinutes } from "@/lib/plan-types";

export function LegRow({
  leg,
  mode,
  routed,
}: {
  leg: PlanLeg | undefined;
  mode: TravelMode;
  routed: boolean;
}) {
  if (!routed || !leg) {
    return (
      <p className="py-2 pl-5 font-mono text-[11px] text-faint">
        {mode === "transit" ? "transit" : "walk"} — no times yet
      </p>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 py-2 pl-5">
      <span className="font-mono text-[11px] text-faint">
        {mode === "transit" ? "transit" : "walk"} {formatMinutes(leg.seconds)}
        {leg.meters > 0 && ` · ${formatDistance(leg.meters)}`}
      </span>
      {leg.transit_steps.map((step) => (
        <span
          key={step}
          className="flex h-5 items-center rounded-full bg-brand-bg px-2 font-mono text-[10.5px] text-brand"
        >
          {step}
        </span>
      ))}
    </div>
  );
}
