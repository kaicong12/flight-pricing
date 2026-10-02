// Queues an itinerary draft; its status arrives via GET /trips/{id}.

import { proxy } from "@/lib/tp-api";

export async function POST(
  _request: Request,
  { params }: RouteContext<"/api/trips/[tripId]/draft">,
) {
  const { tripId } = await params;
  return proxy(`/trips/${encodeURIComponent(tripId)}/draft`, { method: "POST" });
}
