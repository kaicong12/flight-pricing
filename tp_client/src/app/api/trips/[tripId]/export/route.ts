// The trip as a spreadsheet.

import { proxyFile } from "@/lib/tp-api";

export async function GET(_request: Request, { params }: RouteContext<"/api/trips/[tripId]/export">) {
  const { tripId } = await params;
  return proxyFile(`/trips/${encodeURIComponent(tripId)}/export.xlsx`);
}
