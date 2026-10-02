// Undoes a recorded payment.

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
