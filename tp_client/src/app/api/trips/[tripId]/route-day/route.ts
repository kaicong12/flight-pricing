// Route one day. Named route-day rather than nested under days/[n]/route so the file is not
// route/route.ts.

import { proxy } from "@/lib/tp-api";

export async function POST(
  request: Request,
  { params }: RouteContext<"/api/trips/[tripId]/route-day">,
) {
  const { tripId } = await params;
  const day = Number(new URL(request.url).searchParams.get("day") ?? "0");
  if (!Number.isInteger(day) || day < 0) {
    return Response.json({ detail: "day must be a non-negative integer" }, { status: 400 });
  }
  return proxy(`/trips/${encodeURIComponent(tripId)}/days/${day}/route`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: await request.text(),
  });
}
