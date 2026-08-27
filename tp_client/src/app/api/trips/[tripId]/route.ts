// Ingestion progress for one trip, polled by the client.

import { proxy } from "@/lib/tp-api";

export async function GET(_request: Request, { params }: RouteContext<"/api/trips/[tripId]">) {
  const { tripId } = await params;
  return proxy(`/trips/${encodeURIComponent(tripId)}`);
}

export async function DELETE(_request: Request, { params }: RouteContext<"/api/trips/[tripId]">) {
  const { tripId } = await params;
  return proxy(`/trips/${encodeURIComponent(tripId)}`, { method: "DELETE" });
}
