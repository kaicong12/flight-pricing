// Upload new trip: a trip exported from here comes back as a new one the caller owns.

import { proxy } from "@/lib/tp-api";

export async function POST(request: Request) {
  return proxy("/uploads", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: await request.text(),
  });
}
