"""Sign-in, sessions, and the gate on every endpoint."""

import base64
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from conftest import plan_body
from fastapi.routing import APIRoute
from sqlalchemy import select

from libs.auth import AuthError, GoogleIdentity, exchange_code, upsert_user, user_for_token
from libs.db import User, UserSession, UserTrip
from libs.settings import Settings
from tp_api.deps import current_user, require_trip_access
from tp_api.main import app

WHO = GoogleIdentity(sub="118…420", email="friend@example.com", name="A Friend",
                     picture="https://lh3.googleusercontent.com/a/x=s96-c")

# Every route that may be reached without a session. Anything else added here is a decision, not an
# oversight: /auth/url and /auth/google are sign-in itself, and the other two must not touch the
# database.
OPEN_ROUTES = {("GET", "/auth/url"), ("POST", "/auth/google"),
               ("GET", "/health"), ("GET", "/metrics")}


def _api_routes(routes):
    """This FastAPI version keeps an included router nested rather than flattening its routes."""
    for r in routes:
        if isinstance(r, APIRoute):
            yield r
        elif type(r).__name__ == "_IncludedRouter":
            yield from _api_routes(r.original_router.routes)


def _dep_names(dependant):
    out = []
    for d in dependant.dependencies:
        out.append(getattr(d.call, "__name__", str(d.call)))
        out += _dep_names(d)
    return out


class TestEveryEndpointIsClosed:
    def test_only_the_known_routes_are_open(self):
        open_now = set()
        for r in _api_routes(app.routes):
            if current_user.__name__ not in _dep_names(r.dependant):
                open_now |= {(m, r.path) for m in r.methods if m != "HEAD"}
        assert open_now == OPEN_ROUTES

    def test_every_trip_route_checks_access(self):
        for r in _api_routes(app.routes):
            if "{trip_id}" in r.path:
                assert require_trip_access.__name__ in _dep_names(r.dependant), r.path


class TestSession:
    def test_a_valid_token_resolves_to_its_user(self, db, user):
        assert user_for_token(db, "test-session-token").user_id == user.user_id

    def test_an_unknown_token_is_nobody(self, db, user):
        assert user_for_token(db, "not-a-token") is None

    def test_an_expired_token_is_nobody(self, db, user):
        db.add(UserSession(token="stale", user_id=user.user_id,
                           expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        db.commit()
        assert user_for_token(db, "stale") is None

    def test_no_header_is_a_401(self, anon_client):
        assert anon_client.get("/trips").status_code == 401

    def test_a_bad_token_is_a_401(self, anon_client):
        anon_client.headers["Authorization"] = "Bearer nope"
        assert anon_client.get("/trips").status_code == 401

    def test_me_returns_the_signed_in_user(self, client, user):
        body = client.get("/auth/me").json()
        assert body == {"user_id": user.user_id, "email": user.email, "name": user.name,
                        "picture": user.picture}

    def test_signing_out_revokes_only_that_token(self, client, db, user):
        db.add(UserSession(token="other-browser", user_id=user.user_id,
                           expires_at=datetime.now(UTC) + timedelta(days=1)))
        db.commit()

        assert client.delete("/auth/session").status_code == 204

        assert user_for_token(db, "test-session-token") is None
        assert user_for_token(db, "other-browser") is not None
        assert client.get("/auth/me").status_code == 401


class TestUpsert:
    def test_a_first_sign_in_creates_the_user(self, db):
        user = upsert_user(db, WHO)
        db.commit()
        assert user.user_id and user.google_sub == WHO.sub and user.email == WHO.email

    def test_a_second_sign_in_reuses_the_row_and_refreshes_the_profile(self, db):
        first = upsert_user(db, WHO)
        db.commit()

        renamed = GoogleIdentity(sub=WHO.sub, email="new@example.com", name="Renamed",
                                 picture=None)
        again = upsert_user(db, renamed)
        db.commit()

        assert again.user_id == first.user_id
        assert db.scalars(select(User)).all() == [again]
        assert (again.email, again.name, again.picture) == ("new@example.com", "Renamed", None)


REDIRECT = "http://localhost:3000/api/auth/callback"


def fake_google(monkeypatch, status, body, client_id="ours", redirect_uri=REDIRECT):
    """Stand in for Google's token endpoint. Settings is patched where libs.auth reads it, because
    settings() is lru_cached and a pydantic model's fields are not settable on the class. Every field
    is passed explicitly: Settings reads the repo-root .env, so a default here would make the test
    depend on whoever is running it."""
    monkeypatch.setattr("libs.auth.settings",
                        lambda: Settings(google_auth_client_id=client_id,
                                         google_auth_client_secret="secret",
                                         google_auth_redirect_uri=redirect_uri))

    class Resp:
        status_code = status
        text = json.dumps(body)

        def json(self):
            return body

    monkeypatch.setattr("libs.auth.client",
                        lambda: type("C", (), {"post": lambda *a, **k: Resp()})())


def id_token(claims):
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


class TestAuthUrl:
    def test_it_carries_our_client_redirect_and_state(self, monkeypatch, anon_client):
        fake_google(monkeypatch, 200, {}, client_id="cid.apps.googleusercontent.com")
        url = anon_client.get("/auth/url", params={"state": "s" * 12}).json()["url"]

        q = parse_qs(urlparse(url).query)
        assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
        assert q["client_id"] == ["cid.apps.googleusercontent.com"]
        assert q["redirect_uri"] == [REDIRECT]
        assert q["state"] == ["s" * 12]
        assert q["response_type"] == ["code"]
        assert q["scope"] == ["openid email profile"]
        # Without both of these a returning user comes back with no refresh_token.
        assert q["access_type"] == ["offline"] and q["prompt"] == ["consent"]

    def test_a_short_state_is_rejected(self, anon_client):
        assert anon_client.get("/auth/url", params={"state": "abc"}).status_code == 422

    def test_no_client_configured_is_a_503(self, monkeypatch, anon_client):
        fake_google(monkeypatch, 200, {}, client_id=None)
        assert anon_client.get("/auth/url", params={"state": "s" * 12}).status_code == 503

    def test_no_redirect_uri_configured_is_a_503(self, monkeypatch, anon_client):
        """There is no default: a localhost one would let a deploy that forgot the variable build a
        consent URL pointing at localhost and fail later as a redirect_uri_mismatch."""
        fake_google(monkeypatch, 200, {}, redirect_uri=None)
        assert anon_client.get("/auth/url", params={"state": "s" * 12}).status_code == 503

    def test_the_exchange_also_refuses_without_a_redirect_uri(self, monkeypatch):
        fake_google(monkeypatch, 200, {}, redirect_uri=None)
        with pytest.raises(AuthError, match="not configured"):
            exchange_code("4/0Ax")


class TestExchange:
    def test_a_rejected_code_is_an_auth_error(self, monkeypatch):
        fake_google(monkeypatch, 400, {"error": "invalid_grant"})
        with pytest.raises(AuthError, match="invalid_grant"):
            exchange_code("4/0Aused")

    def test_an_id_token_for_another_client_is_rejected(self, monkeypatch):
        fake_google(monkeypatch, 200, {
            "id_token": id_token({"sub": "1", "email": "a@b.c", "aud": "someone-else"})})
        with pytest.raises(AuthError, match="different client"):
            exchange_code("4/0Ax")

    def test_a_response_with_no_email_is_rejected(self, monkeypatch):
        fake_google(monkeypatch, 200, {"id_token": id_token({"sub": "1", "aud": "ours"})})
        with pytest.raises(AuthError, match="no email"):
            exchange_code("4/0Ax")

    def test_the_claims_become_the_identity(self, monkeypatch):
        fake_google(monkeypatch, 200, {"id_token": id_token(
            {"sub": WHO.sub, "email": WHO.email, "name": WHO.name, "picture": WHO.picture,
             "aud": "ours"})})
        assert exchange_code("4/0Ax") == WHO

    def test_a_name_and_picture_google_did_not_send_are_none(self, monkeypatch):
        """Google documents both as "might be provided", so neither may be assumed."""
        fake_google(monkeypatch, 200, {"id_token": id_token(
            {"sub": "1", "email": "a@b.c", "aud": "ours"})})
        who = exchange_code("4/0Ax")
        assert (who.name, who.picture) == (None, None)


class TestTripsAreScopedToTheirUser:
    def test_creating_a_trip_grants_the_creator_access(self, client, db, user):
        trip_id = client.post("/initiate-plan", json=plan_body()).json()["trip_id"]
        assert db.get(UserTrip, (user.user_id, trip_id)) is not None

    def test_another_users_trip_is_a_404_not_a_403(self, client, db, user):
        trip_id = client.post("/initiate-plan", json=plan_body()).json()["trip_id"]
        db.add(User(user_id="u-other", google_sub="sub-other", email="other@example.com"))
        db.add(UserSession(token="other-token", user_id="u-other",
                           expires_at=datetime.now(UTC) + timedelta(days=1)))
        db.commit()
        client.headers["Authorization"] = "Bearer other-token"

        # 404 everywhere, so the gate cannot be used to discover which trip ids exist.
        assert client.get(f"/trips/{trip_id}").status_code == 404
        assert client.get(f"/trips/{trip_id}/shortlist").status_code == 404
        assert client.get(f"/trips/{trip_id}/itinerary").status_code == 404
        assert client.delete(f"/trips/{trip_id}").status_code == 404
        assert client.get("/trips").json() == []
