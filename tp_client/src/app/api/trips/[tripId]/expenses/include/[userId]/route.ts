// Costs from before someone was shared with, and re-splitting the chosen ones with them.

import { proxy } from "@/lib/tp-api";

export async function GET(
  _request: Request,
  { params }: RouteContext<"/api/trips/[tripId]/expenses/include/[userId]">,
) {
  const { tripId, userId } = await params;
  return proxy(
    `/trips/${encodeURIComponent(tripId)}/expenses/include/${encodeURIComponent(userId)}`,
  );
}

export async function POST(
  request: Request,
  { params }: RouteContext<"/api/trips/[tripId]/expenses/include/[userId]">,
) {
  const { tripId, userId } = await params;
  return proxy(
    `/trips/${encodeURIComponent(tripId)}/expenses/include/${encodeURIComponent(userId)}`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: await request.text(),
    },
  );
}
