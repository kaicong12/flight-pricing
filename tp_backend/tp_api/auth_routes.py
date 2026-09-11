"""Sign-in endpoints. tp_client owns the cookie; this owns the Google exchange and the session row.

The browser never reaches these directly: /api/auth/callback in tp_client posts the code here,
because the client secret and the database both live on this side.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from libs.auth import (
    AuthError,
    end_session,
    exchange_code,
    google_auth_url,
    start_session,
    upsert_user,
)
from libs.db import User
from tp_api.deps import current_user, db_session, session_token

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger("tp_api")

Db = Annotated[Session, Depends(db_session)]
Me = Annotated[User, Depends(current_user)]
Token = Annotated[str, Depends(session_token)]


class GoogleCallback(BaseModel):
    code: str = Field(min_length=1, max_length=512)


class UserOut(BaseModel):
    user_id: str
    email: str
    name: str | None
    picture: str | None


class SessionOut(BaseModel):
    token: str
    user: UserOut


class AuthUrlOut(BaseModel):
    url: str


@router.get("/url", response_model=AuthUrlOut)
def auth_url(state: Annotated[str, Query(min_length=8, max_length=128)]) -> AuthUrlOut:
    """Where tp_client sends the browser. Built here so the redirect_uri has one definition — it has
    to match byte-for-byte in both the authorization request and the exchange below."""
    try:
        return AuthUrlOut(url=google_auth_url(state))
    except AuthError as e:
        raise HTTPException(503, str(e)) from e


@router.post("/google", response_model=SessionOut)
def sign_in_with_google(body: GoogleCallback, db: Db) -> SessionOut:
    try:
        who = exchange_code(body.code)
    except AuthError as e:
        log.warning("google sign-in failed: %s", e)
        raise HTTPException(401, str(e)) from e

    user = upsert_user(db, who)
    db.flush()
    session = start_session(db, user)
    db.commit()
    log.info("signed in user=%s new=%s", user.email, user.created_at == user.updated_at)
    return SessionOut(token=session.token, user=UserOut.model_validate(user, from_attributes=True))


@router.get("/me", response_model=UserOut)
def me(user: Me) -> UserOut:
    return UserOut.model_validate(user, from_attributes=True)


@router.delete("/session", status_code=204)
def sign_out(user: Me, db: Db, token: Token) -> None:
    """Revokes this browser's session only, by deleting the row the token names."""
    end_session(db, token)
    db.commit()
