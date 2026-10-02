// A trip's costs and the balances derived from them.

import { proxy } from "@/lib/tp-api";

export async function GET(
  _request: Request,
  { params }: RouteContext<"/api/trips/[tripId]/expenses">,
) {
  const { tripId } = await params;
  return proxy(`/trips/${encodeURIComponent(tripId)}/expenses`);
}

export async function POST(
  request: Request,
  { params }: RouteContext<"/api/trips/[tripId]/expenses">,
) {
  const { tripId } = await params;
  return proxy(`/trips/${encodeURIComponent(tripId)}/expenses`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: await request.text(),
  });
}
