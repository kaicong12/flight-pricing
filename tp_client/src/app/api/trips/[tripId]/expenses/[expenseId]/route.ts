// One cost. PUT restates it whole, including its shares — a correction is not a patch.

import { proxy } from "@/lib/tp-api";

export async function PUT(
  request: Request,
  { params }: RouteContext<"/api/trips/[tripId]/expenses/[expenseId]">,
) {
  const { tripId, expenseId } = await params;
  return proxy(
    `/trips/${encodeURIComponent(tripId)}/expenses/${encodeURIComponent(expenseId)}`,
    {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: await request.text(),
    },
  );
}

export async function DELETE(
  _request: Request,
  { params }: RouteContext<"/api/trips/[tripId]/expenses/[expenseId]">,
) {
  const { tripId, expenseId } = await params;
  return proxy(
    `/trips/${encodeURIComponent(tripId)}/expenses/${encodeURIComponent(expenseId)}`,
    { method: "DELETE" },
  );
}
