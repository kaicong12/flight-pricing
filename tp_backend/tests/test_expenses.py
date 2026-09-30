"""Splitting a cost, and the balances derived from it."""

from datetime import timedelta

import pytest
from conftest import HELSINKI, make_city, make_place, make_trip

from libs.db import City, User, UserTrip
from libs.db.enums import BlockKind, TripRole
from tp_api.expenses.service import split_evenly
from tp_api.schemas import today_utc

TRIP = "trip-money"


def friend(db, trip_id, name, role=TripRole.EDITOR):
    user = User(user_id=f"u-{name.lower()}", google_sub=f"sub-{name}",
                email=f"{name.lower()}@example.com", name=name)
    db.add(user)
    db.add(UserTrip(user_id=user.user_id, trip_id=trip_id, role=role))
    db.commit()
    return user.user_id


@pytest.fixture
def trip(db, user):
    make_city(db)
    make_trip(db, TRIP)
    db.add(UserTrip(user_id=user.user_id, trip_id=TRIP, role=TripRole.OWNER))
    db.commit()
    return TRIP


def cost(**kw):
    return {"description": "Dinner", "amount_cents": 9000, "currency": "EUR",
            "spent_on": today_utc().isoformat(), "payer_id": "u-test",
            "participants": ["u-test"]} | kw


class TestSplitEvenly:
    def test_the_parts_add_up_to_the_whole(self):
        for amount in (1, 100, 1000, 9999, 12345):
            for people in range(1, 8):
                parts = split_evenly(amount, [f"u{i}" for i in range(people)])
                assert sum(parts.values()) == amount

    def test_the_odd_minor_units_go_to_the_first_participants(self):
        assert split_evenly(1000, ["a", "b", "c"]) == {"a": 334, "b": 333, "c": 333}


class TestAddingACost:
    def test_an_even_split_reaches_everyone_named(self, client, trip, db):
        bob = friend(db, trip, "Bob")
        body = cost(amount_cents=1000, participants=["u-test", bob])
        r = client.post(f"/trips/{trip}/expenses", json=body)
        assert r.status_code == 200, r.text
        assert {s["user_id"]: s["amount_cents"] for s in r.json()["shares"]} == {
            "u-test": 500, bob: 500}

    def test_exact_shares_must_add_up(self, client, trip, db):
        bob = friend(db, trip, "Bob")
        body = cost(amount_cents=1000,
                    shares=[{"user_id": "u-test", "amount_cents": 400},
                            {"user_id": bob, "amount_cents": 400}], participants=[])
        assert client.post(f"/trips/{trip}/expenses", json=body).status_code == 422

    def test_exact_shares_are_kept_as_given(self, client, trip, db):
        bob = friend(db, trip, "Bob")
        body = cost(amount_cents=1000, participants=[],
                    shares=[{"user_id": "u-test", "amount_cents": 250},
                            {"user_id": bob, "amount_cents": 750}])
        r = client.post(f"/trips/{trip}/expenses", json=body)
        assert {s["user_id"]: s["amount_cents"] for s in r.json()["shares"]} == {
            "u-test": 250, bob: 750}

    def test_a_split_and_exact_shares_are_not_both_accepted(self, client, trip):
        body = cost(shares=[{"user_id": "u-test", "amount_cents": 9000}])
        assert client.post(f"/trips/{trip}/expenses", json=body).status_code == 422

    def test_someone_not_on_the_trip_cannot_be_split_with(self, client, trip, db):
        db.add(User(user_id="u-outsider", google_sub="sub-out", email="out@example.com",
                    name="Outsider"))
        db.commit()
        body = cost(participants=["u-test", "u-outsider"])
        r = client.post(f"/trips/{trip}/expenses", json=body)
        assert r.status_code == 422
        assert "not on this trip" in r.text

    def test_a_cost_names_the_block_it_was_for(self, client, trip, db):
        place = make_place(db, place_id="p-museum", name="The Museum")
        client.put(f"/trips/{trip}/itinerary", json={"days": [{"day_index": 0, "items": [
            {"kind": BlockKind.PLACE, "place_id": place, "start_min": 600,
             "duration_min": 90}]}]})
        r = client.post(f"/trips/{trip}/expenses", json=cost(place_id=place))
        assert r.status_code == 200, r.text
        assert r.json()["block_title"] == "The Museum"
        assert r.json()["day_index"] == 0

    def test_a_cost_names_one_block_not_two(self, client, trip):
        body = cost(place_id="p1", block_id="b1")
        assert client.post(f"/trips/{trip}/expenses", json=body).status_code == 422

    def test_a_viewer_cannot_add_one(self, anon_client, db, trip):
        from datetime import UTC, datetime

        from libs.db import UserSession
        viewer = friend(db, trip, "Vera", role=TripRole.VIEWER)
        db.add(UserSession(token="vera-token", user_id=viewer,
                           expires_at=datetime.now(UTC) + timedelta(days=1)))
        db.commit()
        anon_client.headers["Authorization"] = "Bearer vera-token"
        r = anon_client.post(f"/trips/{trip}/expenses", json=cost(payer_id=viewer,
                                                                 participants=[viewer]))
        assert r.status_code == 403


class TestBalances:
    def test_one_person_paying_for_everyone_leaves_the_others_owing(self, client, trip, db):
        bob, cara = friend(db, trip, "Bob"), friend(db, trip, "Cara")
        client.post(f"/trips/{trip}/expenses",
                    json=cost(amount_cents=3000, participants=["u-test", bob, cara]))

        pile = client.get(f"/trips/{trip}/expenses").json()["balances"][0]
        assert pile["currency"] == "EUR"
        net = {m["user_id"]: m["net_cents"] for m in pile["members"]}
        assert net == {"u-test": 2000, bob: -1000, cara: -1000}
        assert sum(net.values()) == 0

    def test_a_member_who_never_paid_still_appears(self, client, trip, db):
        """The commonest real shape, and the one an outer join drops."""
        bob = friend(db, trip, "Bob")
        client.post(f"/trips/{trip}/expenses",
                    json=cost(amount_cents=1000, participants=["u-test", bob]))
        members = client.get(f"/trips/{trip}/expenses").json()["balances"][0]["members"]
        assert {m["user_id"] for m in members} == {"u-test", bob}
        assert next(m for m in members if m["user_id"] == bob)["paid_cents"] == 0

    def test_each_currency_is_its_own_pile(self, client, trip, db):
        bob = friend(db, trip, "Bob")
        both = ["u-test", bob]
        client.post(f"/trips/{trip}/expenses",
                    json=cost(amount_cents=1000, currency="EUR", participants=both))
        client.post(f"/trips/{trip}/expenses",
                    json=cost(amount_cents=40000, currency="NOK", payer_id=bob,
                              participants=both))

        piles = {p["currency"]: p for p in client.get(f"/trips/{trip}/expenses").json()["balances"]}
        assert set(piles) == {"EUR", "NOK"}
        assert {m["user_id"]: m["net_cents"] for m in piles["EUR"]["members"]} == {
            "u-test": 500, bob: -500}
        assert {m["user_id"]: m["net_cents"] for m in piles["NOK"]["members"]} == {
            "u-test": -20000, bob: 20000}

    def test_settling_up_clears_the_balance(self, client, trip, db):
        bob = friend(db, trip, "Bob")
        client.post(f"/trips/{trip}/expenses",
                    json=cost(amount_cents=1000, participants=["u-test", bob]))
        r = client.post(f"/trips/{trip}/settlements",
                        json={"from_user_id": bob, "to_user_id": "u-test", "amount_cents": 500,
                              "currency": "EUR", "paid_on": today_utc().isoformat()})
        assert r.status_code == 200, r.text

        pile = client.get(f"/trips/{trip}/expenses").json()["balances"][0]
        assert all(m["net_cents"] == 0 for m in pile["members"])
        assert pile["transfers"] == []

    def test_a_part_payment_leaves_the_rest_owing(self, client, trip, db):
        bob = friend(db, trip, "Bob")
        client.post(f"/trips/{trip}/expenses",
                    json=cost(amount_cents=1000, participants=["u-test", bob]))
        client.post(f"/trips/{trip}/settlements",
                    json={"from_user_id": bob, "to_user_id": "u-test", "amount_cents": 200,
                          "currency": "EUR", "paid_on": today_utc().isoformat()})
        pile = client.get(f"/trips/{trip}/expenses").json()["balances"][0]
        assert {m["user_id"]: m["net_cents"] for m in pile["members"]} == {
            "u-test": 300, bob: -300}
        assert pile["transfers"] == [{"from_user_id": bob, "to_user_id": "u-test",
                                      "amount_cents": 300}]

    def test_the_transfers_never_outnumber_the_people(self, client, trip, db):
        who = ["u-test", friend(db, trip, "Bob"), friend(db, trip, "Cara"),
               friend(db, trip, "Dan")]
        for payer in who:
            client.post(f"/trips/{trip}/expenses",
                        json=cost(amount_cents=1234, payer_id=payer, participants=who))
        client.post(f"/trips/{trip}/expenses",
                    json=cost(amount_cents=50000, payer_id=who[1], participants=who))

        pile = client.get(f"/trips/{trip}/expenses").json()["balances"][0]
        assert len(pile["transfers"]) <= len(who) - 1
        assert sum(m["net_cents"] for m in pile["members"]) == 0
        for t in pile["transfers"]:
            assert t["amount_cents"] > 0

    def test_a_deleted_cost_leaves_the_balance(self, client, trip, db):
        bob = friend(db, trip, "Bob")
        r = client.post(f"/trips/{trip}/expenses",
                        json=cost(amount_cents=1000, participants=["u-test", bob]))
        assert client.delete(
            f"/trips/{trip}/expenses/{r.json()['expense_id']}").status_code == 204
        tab = client.get(f"/trips/{trip}/expenses").json()
        assert tab["expenses"] == []
        assert tab["balances"] == []

    def test_editing_a_cost_restates_its_shares(self, client, trip, db):
        bob = friend(db, trip, "Bob")
        r = client.post(f"/trips/{trip}/expenses",
                        json=cost(amount_cents=1000, participants=["u-test", bob]))
        eid = r.json()["expense_id"]
        assert client.put(f"/trips/{trip}/expenses/{eid}",
                          json=cost(amount_cents=600, participants=["u-test"])).status_code == 200
        pile = client.get(f"/trips/{trip}/expenses").json()["balances"][0]
        assert {m["user_id"]: m["net_cents"] for m in pile["members"]} == {"u-test": 0}


class TestTheTab:
    def test_it_suggests_the_anchor_citys_currency_first(self, client, trip, db):
        db.get(City, HELSINKI).country = "NO"
        db.commit()
        assert client.get(f"/trips/{trip}/expenses").json()["currency"] == "NOK"

    def test_then_whatever_the_trip_last_spent_in(self, client, trip):
        client.post(f"/trips/{trip}/expenses", json=cost(currency="NOK"))
        assert client.get(f"/trips/{trip}/expenses").json()["currency"] == "NOK"

    def test_it_carries_the_trips_people(self, client, trip, db):
        friend(db, trip, "Bob")
        members = client.get(f"/trips/{trip}/expenses").json()["members"]
        assert {m["name"] for m in members} == {"A Friend", "Bob"}
