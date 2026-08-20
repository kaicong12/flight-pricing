// Creates a trip and kicks off city ingestion.

import { proxy } from "@/lib/tp-api";

export async function POST(request: Request) {
  return proxy("/initiate-plan", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: await request.text(),
  });
}
