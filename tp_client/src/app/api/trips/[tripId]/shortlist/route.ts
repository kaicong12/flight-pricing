// The ranked shortlist for one trip's city.

import { proxy } from "@/lib/tp-api";

export async function GET(
  request: Request,
  { params }: RouteContext<"/api/trips/[tripId]/shortlist">,
) {
  const { tripId } = await params;
  const from = new URL(request.url).searchParams;
  const query = new URLSearchParams({ limit: from.get("limit") ?? "40" });
  for (const key of ["offset", "category", "source", "q"]) {
    if (from.get(key)) query.set(key, from.get(key)!);
  }
  return proxy(`/trips/${encodeURIComponent(tripId)}/shortlist?${query}`);
}
