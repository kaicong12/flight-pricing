// Bounces a visitor with no session cookie to /login.
//
// Optimistic only: this runs on prefetches too, so it checks that a cookie exists and never whether
// it is still valid. tp_api's 401 is the real gate — see src/lib/tp-api.ts.

import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { SESSION_COOKIE } from "@/lib/cookies";

export function proxy(request: NextRequest) {
  if (request.cookies.has(SESSION_COOKIE)) return NextResponse.next();
  return NextResponse.redirect(new URL("/login", request.url));
}

export const config = {
  // Everything except /login, the auth handlers themselves, and Next's own assets.
  matcher: ["/((?!login|api/auth|_next|favicon.ico|icon.svg).*)"],
};
