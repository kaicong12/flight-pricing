"""Sharing a trip, and what each role may then do with it."""

from datetime import UTC, datetime, timedelta

import pytest
from conftest import make_place, plan_body
from sqlalchemy.exc import IntegrityError

from libs.db import User, UserSession, UserTrip
from libs.db.enums import TripRole


def make_trip(client, **kw):
    return client.post("/initiate-plan", json=plan_body(**kw)).json()["trip_id"]


@pytest.fixture
def friend(db):
    """A second signed-in account, with its own session token."""
    u = User(user_id="u-friend", google_sub="sub-friend", email="second@example.com",
             name="Bo Nordmann", picture="https://lh3.googleusercontent.com/a/bo=s96-c")
    db.add(u)
    db.add(UserSession(token="friend-token", user_id=u.user_id,
                       expires_at=datetime.now(UTC) + timedelta(days=1)))
    db.commit()
    return u


def seen_by(client, token):
    """Swap whose session the client carries. One TestClient, so this is the only way to be someone
    else, and it is deliberately explicit at the call site."""
    client.headers["Authorization"] = f"Bearer {token}"
    return client


def share(client, trip, user_id, role=TripRole.EDITOR):
    return client.post(f"/trips/{trip}/members", json={"user_id": user_id, "role": role})


class TestAccess:
    def test_a_trip_is_invisible_until_it_is_shared(self, client, friend):
        trip = make_trip(client)
        seen_by(client, "friend-token")
        assert client.get(f"/trips/{trip}").status_code == 404
        assert client.get("/trips").json() == []

    def test_sharing_makes_it_visible_to_the_other_user(self, client, friend):
        trip = make_trip(client)
        assert share(client, trip, friend.user_id).status_code == 200

        seen_by(client, "friend-token")
        assert client.get(f"/trips/{trip}").status_code == 200
        assert [t["trip_id"] for t in client.get("/trips").json()] == [trip]

    def test_the_creator_is_the_owner(self, client, db):
        trip = make_trip(client)
        assert db.get(UserTrip, ("u-test", trip)).role == TripRole.OWNER
        assert client.get(f"/trips/{trip}").json()["your_role"] == "owner"

    def test_each_side_is_told_its_own_role(self, client, friend):
        """The UI hides what would only 403, so the role travels with the trip."""
        trip = make_trip(client)
        share(client, trip, friend.user_id, TripRole.VIEWER)
        assert client.get(f"/trips/{trip}").json()["your_role"] == "owner"
        assert client.get("/trips").json()[0]["your_role"] == "owner"

        seen_by(client, "friend-token")
        assert client.get(f"/trips/{trip}").json()["your_role"] == "viewer"
        assert client.get("/trips").json()[0]["your_role"] == "viewer"

    def test_members_lists_everyone_with_their_role(self, client, friend):
        trip = make_trip(client)
        share(client, trip, friend.user_id, TripRole.VIEWER)
        got = [(m["email"], m["role"]) for m in client.get(f"/trips/{trip}/members").json()]
        assert got == [("friend@example.com", "owner"), ("second@example.com", "viewer")]


class TestWhatAnEditorMay:
    def test_edit_the_itinerary(self, client, db, friend):
        trip = make_trip(client)
        make_place(db, place_id="p1")
        share(client, trip, friend.user_id, TripRole.EDITOR)

        seen_by(client, "friend-token")
        r = client.put(f"/trips/{trip}/itinerary", json={"days": [
            {"day_index": 0, "items": [{"place_id": "p1", "start_min": 900,
                                        "duration_min": 60}]}]})
        assert r.status_code == 200

    def test_not_rename_it(self, client, friend):
        trip = make_trip(client)
        share(client, trip, friend.user_id, TripRole.EDITOR)
        seen_by(client, "friend-token")
        assert client.patch(f"/trips/{trip}", json={"name": "mine now"}).status_code == 403

    def test_not_delete_it(self, client, friend):
        trip = make_trip(client)
        share(client, trip, friend.user_id, TripRole.EDITOR)
        seen_by(client, "friend-token")
        assert client.delete(f"/trips/{trip}").status_code == 403

    def test_not_share_it_further(self, client, friend, db):
        trip = make_trip(client)
        share(client, trip, friend.user_id, TripRole.EDITOR)
        third = User(user_id="u-third", google_sub="sub-third", email="third@example.com")
        db.add(third)
        db.commit()

        seen_by(client, "friend-token")
        assert share(client, trip, "u-third").status_code == 403


class TestWhatAViewerMay:
    def test_read_the_trip_and_route_a_day(self, client, db, friend):
        trip = make_trip(client)
        make_place(db, place_id="p1")
        client.put(f"/trips/{trip}/itinerary", json={"days": [
            {"day_index": 0, "items": [{"place_id": "p1", "start_min": 900,
                                        "duration_min": 60}]}]})
        share(client, trip, friend.user_id, TripRole.VIEWER)

        seen_by(client, "friend-token")
        assert client.get(f"/trips/{trip}/shortlist").status_code == 200
        # Routing stores nothing, so a viewer may do it — otherwise the map draws no line.
        assert client.post(f"/trips/{trip}/days/0/route").status_code == 200

    def test_not_change_the_itinerary(self, client, friend):
        trip = make_trip(client)
        share(client, trip, friend.user_id, TripRole.VIEWER)
        seen_by(client, "friend-token")
        r = client.put(f"/trips/{trip}/itinerary", json={"days": [
            {"day_index": 0, "items": []}]})
        assert r.status_code == 403

    def test_not_draft_days(self, client, friend):
        trip = make_trip(client)
        share(client, trip, friend.user_id, TripRole.VIEWER)
        seen_by(client, "friend-token")
        assert client.post(f"/trips/{trip}/draft").status_code == 403

    def test_not_dismiss_a_place(self, client, friend):
        trip = make_trip(client)
        share(client, trip, friend.user_id, TripRole.VIEWER)
        seen_by(client, "friend-token")
        r = client.post(f"/trips/{trip}/dismissals", json={"place_id": "p1"})
        assert r.status_code == 403

    def test_not_add_a_place(self, client, friend):
        trip = make_trip(client)
        share(client, trip, friend.user_id, TripRole.VIEWER)
        seen_by(client, "friend-token")
        r = client.post(f"/trips/{trip}/places", json={"place_id": "p1"})
        assert r.status_code == 403

    def test_not_even_search_for_one(self, client, friend):
        """Searching spends a Places call, so a viewer is stopped before it, not after."""
        trip = make_trip(client)
        share(client, trip, friend.user_id, TripRole.VIEWER)
        seen_by(client, "friend-token")
        assert client.get(f"/trips/{trip}/places/search", params={"q": "oodi"}).status_code == 403


class TestOwnership:
    def test_a_request_cannot_hand_out_ownership(self, client, friend):
        trip = make_trip(client)
        r = share(client, trip, friend.user_id, "owner")
        assert r.status_code == 422

    def test_the_owner_cannot_be_demoted(self, client, user):
        trip = make_trip(client)
        assert share(client, trip, user.user_id, TripRole.VIEWER).status_code == 409

    def test_the_owner_cannot_be_removed(self, client, user):
        trip = make_trip(client)
        assert client.delete(f"/trips/{trip}/members/{user.user_id}").status_code == 409

    def test_the_database_refuses_a_second_owner(self, client, db, friend):
        trip = make_trip(client)
        db.add(UserTrip(user_id=friend.user_id, trip_id=trip, role=TripRole.OWNER))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    def test_an_unknown_role_is_rejected(self, client, friend):
        trip = make_trip(client)
        assert share(client, trip, friend.user_id, "admin").status_code == 422

    def test_sharing_with_a_stranger_is_a_404(self, client):
        trip = make_trip(client)
        assert share(client, trip, "u-nobody").status_code == 404


class TestUnsharing:
    def test_the_owner_removes_a_member(self, client, friend):
        trip = make_trip(client)
        share(client, trip, friend.user_id)
        assert client.delete(f"/trips/{trip}/members/{friend.user_id}").status_code == 204

        seen_by(client, "friend-token")
        assert client.get(f"/trips/{trip}").status_code == 404

    def test_a_member_may_leave(self, client, friend):
        trip = make_trip(client)
        share(client, trip, friend.user_id)
        seen_by(client, "friend-token")
        assert client.delete(f"/trips/{trip}/members/{friend.user_id}").status_code == 204

    def test_a_member_may_not_remove_anyone_else(self, client, db, friend):
        trip = make_trip(client)
        share(client, trip, friend.user_id)
        third = User(user_id="u-third", google_sub="sub-third", email="third@example.com")
        db.add(third)
        db.commit()
        share(client, trip, "u-third")

        seen_by(client, "friend-token")
        assert client.delete(f"/trips/{trip}/members/u-third").status_code == 403

    def test_removing_someone_who_is_not_a_member_is_a_404(self, client, friend):
        trip = make_trip(client)
        assert client.delete(f"/trips/{trip}/members/{friend.user_id}").status_code == 404


class TestUserSearch:
    def test_finds_by_email_and_by_name(self, client, friend):
        assert [u["email"] for u in client.get("/users/search?q=second@").json()] \
            == ["second@example.com"]
        assert [u["name"] for u in client.get("/users/search?q=nordmann").json()] \
            == ["Bo Nordmann"]

    def test_never_returns_yourself(self, client, user):
        assert client.get("/users/search?q=friend@example.com").json() == []

    def test_a_one_character_query_is_rejected(self, client):
        assert client.get("/users/search?q=a").status_code == 422

    def test_the_avatar_and_name_the_dropdown_renders_are_returned(self, client, friend):
        got = client.get("/users/search?q=nordmann").json()[0]
        assert got == {"user_id": "u-friend", "email": "second@example.com",
                       "name": "Bo Nordmann",
                       "picture": "https://lh3.googleusercontent.com/a/bo=s96-c"}
