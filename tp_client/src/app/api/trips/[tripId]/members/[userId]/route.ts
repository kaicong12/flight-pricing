// Unshare, or leave a trip someone shared with you.

import { proxy } from "@/lib/tp-api";

export async function DELETE(
  _request: Request,
  { params }: RouteContext<"/api/trips/[tripId]/members/[userId]">,
) {
  const { tripId, userId } = await params;
  return proxy(
    `/trips/${encodeURIComponent(tripId)}/members/${encodeURIComponent(userId)}`,
    { method: "DELETE" },
  );
}
