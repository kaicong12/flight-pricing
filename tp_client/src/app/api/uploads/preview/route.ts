// What an upload would create, and which rows it would leave out. Writes nothing.

import { proxy } from "@/lib/tp-api";

export async function POST(request: Request) {
  return proxy("/uploads/preview", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: await request.text(),
  });
}
