// The ranked shortlist for one trip's city.

import { proxy } from "@/lib/tp-api";

export async function GET(
  request: Request,
  { params }: RouteContext<"/api/trips/[tripId]/shortlist">,
) {
  const { tripId } = await params;
  const from = new URL(request.url).searchParams;
  const query = new URLSearchParams({ limit: from.get("limit") ?? "40" });
  if (from.get("offset")) query.set("offset", from.get("offset")!);
  if (from.get("category")) query.set("category", from.get("category")!);
  return proxy(`/trips/${encodeURIComponent(tripId)}/shortlist?${query}`);
}
