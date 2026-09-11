// Server-side helper for talking to tp_api. Only route handlers and server components import this,
// so no key, upstream URL or session token ever reaches client JS.

import { cookies } from "next/headers";

import { SESSION_COOKIE } from "@/lib/cookies";

const BASE = process.env.TP_API_URL ?? "http://127.0.0.1:8000";

// The Response constructor rejects a body on any of these, so a 204 from tp_api must stay bodyless.
const NULL_BODY_STATUSES = new Set([101, 103, 204, 205, 304]);

/** Every tp_api route except sign-in is authed, so the session travels on all of them from here. */
async function authed(init?: RequestInit): Promise<RequestInit> {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  return {
    ...init,
    cache: "no-store",
    headers: { ...init?.headers, ...(token ? { authorization: `Bearer ${token}` } : {}) },
  };
}

/** Proxies one tp_api call, preserving its status code and JSON body. */
export async function proxy(path: string, init?: RequestInit): Promise<Response> {
  let upstream: Response;
  try {
    upstream = await fetch(`${BASE}${path}`, await authed(init));
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
    const r = await fetch(`${BASE}${path}`, await authed());
    return r.ok ? ((await r.json()) as T) : null;
  } catch {
    return null;
  }
}

/** Sign-in only: the one call with no session yet, so it must not read the cookie. */
export async function postAnon<T>(path: string, body: unknown): Promise<T | null> {
  try {
    const r = await fetch(`${BASE}${path}`, {
      method: "POST",
      cache: "no-store",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    return r.ok ? ((await r.json()) as T) : null;
  } catch {
    return null;
  }
}
