// Striking a place off one trip's shortlist, for when Google carries the same venue twice.

import { proxy } from "@/lib/tp-api";

export async function POST(
  request: Request,
  { params }: RouteContext<"/api/trips/[tripId]/dismissals">,
) {
  const { tripId } = await params;
  return proxy(`/trips/${encodeURIComponent(tripId)}/dismissals`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: await request.text(),
  });
}

export async function DELETE(
  request: Request,
  { params }: RouteContext<"/api/trips/[tripId]/dismissals">,
) {
  const { tripId } = await params;
  const placeId = new URL(request.url).searchParams.get("place_id") ?? "";
  return proxy(
    `/trips/${encodeURIComponent(tripId)}/dismissals/${encodeURIComponent(placeId)}`,
    { method: "DELETE" },
  );
}
