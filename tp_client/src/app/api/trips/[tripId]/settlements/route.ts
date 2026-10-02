// Records that someone paid someone back.

import { proxy } from "@/lib/tp-api";

export async function POST(
  request: Request,
  { params }: RouteContext<"/api/trips/[tripId]/settlements">,
) {
  const { tripId } = await params;
  return proxy(`/trips/${encodeURIComponent(tripId)}/settlements`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: await request.text(),
  });
}
