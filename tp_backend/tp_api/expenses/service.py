"""What the expenses endpoints do: split a cost, derive the balances, and suggest the transfers.

Balances are **derived, never stored**. Nothing writes a running total, so no total can drift out of
agreement with the rows it came from, and editing a three-week-old expense needs no recalculation
pass. The derivation is a Python accumulation rather than one aggregate query, because the shapes
that matter here — a member who never paid for anything, a currency only one person spent in — are
exactly the ones an outer join silently drops a row from.
"""

import logging
import uuid
from collections import defaultdict

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from libs.db import Expense, ExpenseShare, ItineraryItem, Settlement, Trip, UserTrip
from tp_api.expenses.schemas import (
    CurrencyBalance,
    ExpenseIn,
    ExpenseOut,
    ExpensesOut,
    MemberBalance,
    SettlementIn,
    SettlementOut,
    ShareOut,
    Transfer,
)
from tp_api.sharing.service import members as trip_members

log = logging.getLogger("tp_api")

# ponytail: enough for where this app has been pointed; extend by hand, EUR otherwise.
COUNTRY_CURRENCY = {
    "AT": "EUR", "AU": "AUD", "BE": "EUR", "CA": "CAD", "CH": "CHF", "CN": "CNY", "CZ": "CZK",
    "DE": "EUR", "DK": "DKK", "EE": "EUR", "ES": "EUR", "FI": "EUR", "FR": "EUR", "GB": "GBP",
    "HK": "HKD", "ID": "IDR", "IE": "EUR", "IS": "ISK", "IT": "EUR", "JP": "JPY", "KR": "KRW",
    "MY": "MYR", "NL": "EUR", "NO": "NOK", "NZ": "NZD", "PH": "PHP", "PL": "PLN", "PT": "EUR",
    "SE": "SEK", "SG": "SGD", "TH": "THB", "TW": "TWD", "US": "USD", "VN": "VND",
}


def split_evenly(amount_cents: int, user_ids: list[str]) -> dict[str, int]:
    """An even split whose parts add up exactly. The odd minor units go to the first participants."""
    base, odd = divmod(amount_cents, len(user_ids))
    return {u: base + (1 if i < odd else 0) for i, u in enumerate(user_ids)}


def _member_ids(db: Session, trip_id: str) -> set[str]:
    return set(db.scalars(select(UserTrip.user_id).where(UserTrip.trip_id == trip_id)))


def _check_people(db: Session, trip_id: str, user_ids: list[str]) -> None:
    outsiders = set(user_ids) - _member_ids(db, trip_id)
    if outsiders:
        raise HTTPException(422, "that person is not on this trip")


def _live(trip_id: str):
    return select(Expense).where(Expense.trip_id == trip_id, Expense.deleted.is_(False))


def _transfers(net: dict[str, int]) -> list[Transfer]:
    """Greedy largest-debt-to-largest-credit. At most n−1 transfers; the true minimum is NP-hard."""
    owed = sorted(((u, n) for u, n in net.items() if n > 0), key=lambda p: (-p[1], p[0]))
    owes = sorted(((u, -n) for u, n in net.items() if n < 0), key=lambda p: (-p[1], p[0]))
    out, i, j = [], 0, 0
    while i < len(owes) and j < len(owed):
        (debtor, debt), (creditor, credit) = owes[i], owed[j]
        pay = min(debt, credit)
        out.append(Transfer(from_user_id=debtor, to_user_id=creditor, amount_cents=pay))
        owes[i], owed[j] = (debtor, debt - pay), (creditor, credit - pay)
        if owes[i][1] == 0:
            i += 1
        if owed[j][1] == 0:
            j += 1
    return out


def _balances(expenses: list[Expense], shares: list[tuple[ExpenseShare, str]],
              settlements: list[Settlement]) -> list[CurrencyBalance]:
    """Paid, owed and settled folded into one net figure per person per currency.

    Paid and owed are accumulated in separate passes on purpose: walking the join of expenses to
    shares would add the payer's whole amount once per participant.
    """
    paid: dict[tuple[str, str], int] = defaultdict(int)
    owed: dict[tuple[str, str], int] = defaultdict(int)
    moved: dict[tuple[str, str], int] = defaultdict(int)
    totals: dict[str, int] = defaultdict(int)

    for e in expenses:
        paid[(e.payer_id, e.currency)] += e.amount_cents
        totals[e.currency] += e.amount_cents
    for share, currency in shares:
        owed[(share.user_id, currency)] += share.amount_cents
        totals.setdefault(currency, 0)
    for s in settlements:
        # Paying down a debt moves the payer's net up and the payee's down, so the two still cancel.
        moved[(s.from_user_id, s.currency)] += s.amount_cents
        moved[(s.to_user_id, s.currency)] -= s.amount_cents
        totals.setdefault(s.currency, 0)

    out = []
    for currency in sorted(totals):
        people = sorted({u for u, c in (*paid, *owed, *moved) if c == currency})
        net = {u: paid[(u, currency)] - owed[(u, currency)] + moved[(u, currency)] for u in people}
        out.append(CurrencyBalance(
            currency=currency,
            total_cents=totals[currency],
            members=[MemberBalance(user_id=u, paid_cents=paid[(u, currency)],
                                   share_cents=owed[(u, currency)],
                                   settled_cents=moved[(u, currency)], net_cents=net[u])
                     for u in people],
            transfers=_transfers(net),
        ))
    return out


def _out(e: Expense, blocks: dict[str, tuple[str, int]]) -> ExpenseOut:
    key = e.place_id or e.block_id
    title, day = blocks.get(key or "", (None, None))
    return ExpenseOut(
        expense_id=e.expense_id, description=e.description, amount_cents=e.amount_cents,
        currency=e.currency, spent_on=e.spent_on, payer_id=e.payer_id, place_id=e.place_id,
        block_id=e.block_id, block_title=title, day_index=day,
        shares=[ShareOut(user_id=s.user_id, amount_cents=s.amount_cents)
                for s in sorted(e.shares, key=lambda s: s.user_id)],
    )


def _blocks(db: Session, trip_id: str) -> dict[str, tuple[str | None, int]]:
    """Title and day of every block a cost could name, keyed by whichever identity it has."""
    items = db.scalars(select(ItineraryItem).where(ItineraryItem.trip_id == trip_id))
    return {item.place_id or item.block_id:
            (item.title or (item.place.name if item.place else None), item.day_index)
            for item in items}


def overview(db: Session, trip_id: str) -> ExpensesOut:
    """The whole tab. Takes a trip_id rather than a Trip so nothing here imports route_planning."""
    trip = db.get(Trip, trip_id)
    if trip is None:
        raise HTTPException(404, "no such trip")
    expenses = db.scalars(
        _live(trip.trip_id).order_by(Expense.spent_on, Expense.created_at)
    ).unique().all()
    shares = db.execute(
        select(ExpenseShare, Expense.currency)
        .join(Expense, Expense.expense_id == ExpenseShare.expense_id)
        .where(Expense.trip_id == trip.trip_id, Expense.deleted.is_(False))
    ).all()
    settlements = db.scalars(
        select(Settlement).where(Settlement.trip_id == trip.trip_id).order_by(Settlement.paid_on)
    ).all()

    blocks = _blocks(db, trip.trip_id)
    return ExpensesOut(
        currency=default_currency(db, trip),
        members=trip_members(db, trip.trip_id),
        expenses=[_out(e, blocks) for e in expenses],
        settlements=[SettlementOut.model_validate(s, from_attributes=True) for s in settlements],
        balances=_balances(list(expenses), shares, list(settlements)),
    )


def default_currency(db: Session, trip: Trip) -> str:
    """What the add form starts on: whatever this trip last spent in, else the anchor's country."""
    last = db.scalars(_live(trip.trip_id).order_by(Expense.created_at.desc()).limit(1)).first()
    if last:
        return last.currency
    return COUNTRY_CURRENCY.get((trip.city.country or "").upper(), "EUR")


def add_expense(db: Session, trip_id: str, body: ExpenseIn) -> ExpenseOut:
    if body.shares:
        amounts = {s.user_id: s.amount_cents for s in body.shares}
    else:
        amounts = split_evenly(body.amount_cents, sorted(body.participants))
    _check_people(db, trip_id, [body.payer_id, *amounts])

    expense = Expense(expense_id=str(uuid.uuid4()), trip_id=trip_id, payer_id=body.payer_id,
                      description=body.description.strip(), amount_cents=body.amount_cents,
                      currency=body.currency, spent_on=body.spent_on, place_id=body.place_id,
                      block_id=body.block_id)
    expense.shares = [ExpenseShare(user_id=u, amount_cents=a) for u, a in amounts.items()]
    db.add(expense)
    db.commit()
    log.info("expense trip=%s %s %d by=%s over=%d",
             trip_id[:8], body.currency, body.amount_cents, body.payer_id[:8], len(amounts))
    return _out(expense, _blocks(db, trip_id))


def include_member(db: Session, trip_id: str, user_id: str) -> int:
    """Extend to a member shared with later every cost that split across everyone at the time.

    "Whoever was there" is what the form means by its default, so a cost entered while the trip was
    solo named one person only because one person was on it. A deliberate subset or an uneven split
    is somebody's own arithmetic and is left alone.
    """
    others = _member_ids(db, trip_id) - {user_id}
    if not others:
        return 0

    people = sorted(others | {user_id})
    touched = 0
    for expense in db.scalars(_live(trip_id)).unique():
        was = {s.user_id: s.amount_cents for s in expense.shares}
        if set(was) != others or was != split_evenly(expense.amount_cents, sorted(was)):
            continue
        expense.shares = [ExpenseShare(user_id=u, amount_cents=a)
                          for u, a in split_evenly(expense.amount_cents, people).items()]
        touched += 1

    if touched:
        db.commit()
        log.info("re-split trip=%s with=%s costs=%d", trip_id[:8], user_id[:8], touched)
    return touched


def _get(db: Session, trip_id: str, expense_id: str) -> Expense:
    expense = db.get(Expense, expense_id)
    if expense is None or expense.trip_id != trip_id or expense.deleted:
        raise HTTPException(404, "no such expense")
    return expense


def edit_expense(db: Session, trip_id: str, expense_id: str, body: ExpenseIn) -> ExpenseOut:
    """Replaces the whole expense including its shares — a correction restates the cost."""
    expense = _get(db, trip_id, expense_id)
    if body.shares:
        amounts = {s.user_id: s.amount_cents for s in body.shares}
    else:
        amounts = split_evenly(body.amount_cents, sorted(body.participants))
    _check_people(db, trip_id, [body.payer_id, *amounts])

    expense.payer_id = body.payer_id
    expense.description = body.description.strip()
    expense.amount_cents = body.amount_cents
    expense.currency = body.currency
    expense.spent_on = body.spent_on
    expense.place_id = body.place_id
    expense.block_id = body.block_id
    expense.shares = [ExpenseShare(user_id=u, amount_cents=a) for u, a in amounts.items()]
    db.commit()
    return _out(expense, _blocks(db, trip_id))


def remove_expense(db: Session, trip_id: str, expense_id: str) -> None:
    """Soft, so a balance someone already settled against can still be explained."""
    _get(db, trip_id, expense_id).deleted = True
    db.commit()


def add_settlement(db: Session, trip_id: str, body: SettlementIn) -> SettlementOut:
    _check_people(db, trip_id, [body.from_user_id, body.to_user_id])
    row = Settlement(settlement_id=str(uuid.uuid4()), trip_id=trip_id,
                     from_user_id=body.from_user_id, to_user_id=body.to_user_id,
                     amount_cents=body.amount_cents, currency=body.currency, paid_on=body.paid_on)
    db.add(row)
    db.commit()
    log.info("settled trip=%s %s %d", trip_id[:8], body.currency, body.amount_cents)
    return SettlementOut.model_validate(row, from_attributes=True)


def remove_settlement(db: Session, trip_id: str, settlement_id: str) -> None:
    row = db.get(Settlement, settlement_id)
    if row is None or row.trip_id != trip_id:
        raise HTTPException(404, "no such payment")
    db.delete(row)
    db.commit()
