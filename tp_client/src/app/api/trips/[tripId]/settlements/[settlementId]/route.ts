// Undoing a recorded payment, for when it was entered against the wrong person.

import { proxy } from "@/lib/tp-api";

export async function DELETE(
  _request: Request,
  { params }: RouteContext<"/api/trips/[tripId]/settlements/[settlementId]">,
) {
  const { tripId, settlementId } = await params;
  return proxy(
    `/trips/${encodeURIComponent(tripId)}/settlements/${encodeURIComponent(settlementId)}`,
    { method: "DELETE" },
  );
}
