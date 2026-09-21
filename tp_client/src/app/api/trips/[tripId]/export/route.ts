// The trip as a spreadsheet. Bytes, so it cannot ride the JSON proxy.

import { proxyFile } from "@/lib/tp-api";

export async function GET(_request: Request, { params }: RouteContext<"/api/trips/[tripId]/export">) {
  const { tripId } = await params;
  return proxyFile(`/trips/${encodeURIComponent(tripId)}/export.xlsx`);
}
