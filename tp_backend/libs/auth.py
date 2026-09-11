"""Google sign-in: code -> tokens -> a user row and a session token.

The id_token's signature is deliberately not verified. Google's guidance for this flow: "since you
are communicating directly with Google over an intermediary-free HTTPS channel and using your
client secret to authenticate yourself to Google, you can be confident that the token you receive
really comes from Google and is valid." That is what keeps a JWT library out of the dependencies.
"""

import base64
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from libs.db import User, UserSession
from libs.http import client
from libs.settings import settings

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = "openid email profile"


class AuthError(RuntimeError):
    """The code could not be turned into a Google identity."""


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str
    name: str | None
    picture: str | None


def google_auth_url(state: str) -> str:
    """Step 1: where the browser goes. tp_client owns `state` because it owns the cookie it lives in.

    The nonce is sent because Google's OIDC guidance asks for one, but nothing checks it coming back:
    replay is what a nonce defends against, and an id_token fetched over our own authenticated
    channel cannot be replayed from elsewhere.
    """
    cfg = settings()
    if not cfg.google_auth_client_id or not cfg.google_auth_redirect_uri:
        raise AuthError("google sign-in is not configured")
    return AUTH_URL + "?" + urlencode({
        "client_id": cfg.google_auth_client_id,
        "redirect_uri": cfg.google_auth_redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
        "nonce": secrets.token_urlsafe(16),
        "access_type": "offline",
        "prompt": "consent",
    })


def _claims(id_token: str) -> dict:
    payload = id_token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def exchange_code(code: str) -> GoogleIdentity:
    """Trade an authorization code for the signed-in user. redirect_uri must match the auth request."""
    cfg = settings()
    if not (cfg.google_auth_client_id and cfg.google_auth_client_secret
            and cfg.google_auth_redirect_uri):
        raise AuthError("google sign-in is not configured")
    try:
        r = client().post(TOKEN_URL, data={
            "code": code,
            "client_id": cfg.google_auth_client_id,
            "client_secret": cfg.google_auth_client_secret,
            "redirect_uri": cfg.google_auth_redirect_uri,
            "grant_type": "authorization_code",
        })
    except httpx.HTTPError as e:
        raise AuthError(f"google token endpoint unreachable: {e}") from e
    if r.status_code != 200:
        # invalid_grant covers a reused code, an expired one and a mismatched redirect_uri alike, so
        # the body is the only thing that tells them apart.
        raise AuthError(f"google rejected the code: {r.status_code} {r.text}")

    id_token = r.json().get("id_token")
    if not id_token:
        raise AuthError("no id_token in the token response — was 'openid' in the scopes?")
    c = _claims(id_token)
    if c.get("aud") != cfg.google_auth_client_id:
        raise AuthError("id_token was issued for a different client")
    if not c.get("email"):
        raise AuthError("no email was granted")
    return GoogleIdentity(sub=c["sub"], email=c["email"], name=c.get("name"),
                          picture=c.get("picture"))


def upsert_user(db: Session, who: GoogleIdentity) -> User:
    """The google sub is the identity; name and picture are refreshed because both drift."""
    user = db.scalars(select(User).where(User.google_sub == who.sub)).first()
    if user is None:
        user = User(user_id=str(uuid4()), google_sub=who.sub, email=who.email)
        db.add(user)
    user.email = who.email
    user.name = who.name
    user.picture = who.picture
    return user


def start_session(db: Session, user: User) -> UserSession:
    s = UserSession(
        token=secrets.token_urlsafe(32),
        user_id=user.user_id,
        expires_at=datetime.now(UTC) + timedelta(days=settings().session_ttl_days),
    )
    db.add(s)
    return s


def user_for_token(db: Session, token: str) -> User | None:
    """The signed-in user, or None if the token is unknown or expired."""
    s = db.get(UserSession, token)
    if s is None or s.expires_at <= datetime.now(UTC):
        return None
    return s.user


def end_session(db: Session, token: str) -> None:
    s = db.get(UserSession, token)
    if s is not None:
        db.delete(s)
