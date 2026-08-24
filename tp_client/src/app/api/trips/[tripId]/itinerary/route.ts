// The user's ordering. PUT replaces whole days, because a drag is a statement about a sequence.

import { proxy } from "@/lib/tp-api";

export async function GET(
  _request: Request,
  { params }: RouteContext<"/api/trips/[tripId]/itinerary">,
) {
  const { tripId } = await params;
  return proxy(`/trips/${encodeURIComponent(tripId)}/itinerary`);
}

export async function PUT(
  request: Request,
  { params }: RouteContext<"/api/trips/[tripId]/itinerary">,
) {
  const { tripId } = await params;
  return proxy(`/trips/${encodeURIComponent(tripId)}/itinerary`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: await request.text(),
  });
}
