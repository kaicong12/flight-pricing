// City typeahead, proxied so the browser never talks to tp_api directly.

import { proxy } from "@/lib/tp-api";

export async function GET(request: Request) {
  const q = new URL(request.url).searchParams.get("q") ?? "";
  return proxy(`/cities/search?q=${encodeURIComponent(q)}&limit=5`);
}
