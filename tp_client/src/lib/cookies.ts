// Cookie names, shared between the edge runtime and the server. Deliberately importless: proxy.ts
// runs where `next/headers` does not exist, so anything reaching it must pull in nothing.

export const SESSION_COOKIE = "tp_session";
export const STATE_COOKIE = "tp_oauth_state";
