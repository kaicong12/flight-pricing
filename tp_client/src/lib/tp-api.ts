// Server-side helper for talking to tp_api. Only route handlers import this, so no key or upstream
// URL ever reaches client JS.

const BASE = process.env.TP_API_URL ?? "http://127.0.0.1:8000";

// The Response constructor rejects a body on any of these, so a 204 from tp_api must stay bodyless.
const NULL_BODY_STATUSES = new Set([101, 103, 204, 205, 304]);

/** Proxies one tp_api call, preserving its status code and JSON body. */
export async function proxy(path: string, init?: RequestInit): Promise<Response> {
  let upstream: Response;
  try {
    upstream = await fetch(`${BASE}${path}`, { ...init, cache: "no-store" });
  } catch {
    return Response.json({ detail: "The planning API is unreachable." }, { status: 502 });
  }
  if (NULL_BODY_STATUSES.has(upstream.status)) {
    return new Response(null, { status: upstream.status });
  }
  const text = await upstream.text();
  return new Response(text || "null", {
    status: upstream.status,
    headers: { "content-type": "application/json" },
  });
}

/** Server-side GET for server components, which need the parsed body rather than a Response. */
export async function getJson<T>(path: string): Promise<T | null> {
  try {
    const r = await fetch(`${BASE}${path}`, { cache: "no-store" });
    return r.ok ? ((await r.json()) as T) : null;
  } catch {
    return null;
  }
}
