// City typeahead, proxied to tp_api.

import { proxy } from "@/lib/tp-api";

export async function GET(request: Request) {
  const q = new URL(request.url).searchParams.get("q") ?? "";
  return proxy(`/cities/search?q=${encodeURIComponent(q)}&limit=5`);
}
