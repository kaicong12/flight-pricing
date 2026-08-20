// Server-side helper for talking to tp_api. Only route handlers import this, so no key or upstream
// URL ever reaches client JS.

const BASE = process.env.TP_API_URL ?? "http://127.0.0.1:8000";

/** Proxies one tp_api call, preserving its status code and JSON body. */
export async function proxy(path: string, init?: RequestInit): Promise<Response> {
  let upstream: Response;
  try {
    upstream = await fetch(`${BASE}${path}`, { ...init, cache: "no-store" });
  } catch {
    return Response.json({ detail: "The planning API is unreachable." }, { status: 502 });
  }
  const text = await upstream.text();
  return new Response(text || "null", {
    status: upstream.status,
    headers: { "content-type": "application/json" },
  });
}
