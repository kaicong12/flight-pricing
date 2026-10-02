// Bounces a visitor with no session cookie to /login. Presence only; tp_api's 401 is the real gate.

import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { SESSION_COOKIE } from "@/lib/cookies";

export function proxy(request: NextRequest) {
  if (request.cookies.has(SESSION_COOKIE)) return NextResponse.next();
  return NextResponse.redirect(new URL("/login", request.url));
}

export const config = {
  matcher: ["/((?!login|api/auth|_next|favicon.ico|icon.svg).*)"],
};
