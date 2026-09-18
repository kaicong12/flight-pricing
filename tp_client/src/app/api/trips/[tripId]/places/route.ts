// Adding a place the ingestion never found: a venue typeahead, and the pick that stores it.

import { proxy } from "@/lib/tp-api";

export async function GET(request: Request, { params }: RouteContext<"/api/trips/[tripId]/places">) {
  const { tripId } = await params;
  const q = new URL(request.url).searchParams.get("q") ?? "";
  return proxy(`/trips/${encodeURIComponent(tripId)}/places/search?q=${encodeURIComponent(q)}`);
}

export async function POST(
  request: Request,
  { params }: RouteContext<"/api/trips/[tripId]/places">,
) {
  const { tripId } = await params;
  return proxy(`/trips/${encodeURIComponent(tripId)}/places`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: await request.text(),
  });
}
