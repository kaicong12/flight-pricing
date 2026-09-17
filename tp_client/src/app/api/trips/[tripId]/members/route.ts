// Who a trip is shared with. POST both shares it and changes an existing member's role.

import { proxy } from "@/lib/tp-api";

export async function GET(
  _request: Request,
  { params }: RouteContext<"/api/trips/[tripId]/members">,
) {
  const { tripId } = await params;
  return proxy(`/trips/${encodeURIComponent(tripId)}/members`);
}

export async function POST(
  request: Request,
  { params }: RouteContext<"/api/trips/[tripId]/members">,
) {
  const { tripId } = await params;
  return proxy(`/trips/${encodeURIComponent(tripId)}/members`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: await request.text(),
  });
}
