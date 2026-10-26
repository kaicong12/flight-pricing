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
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from libs.db import Expense, ExpenseShare, ItineraryItem, Settlement, Trip, UserTrip
from tp_api.expenses.schemas import (
    CurrencyBalance,
    ExpenseIn,
    ExpenseOut,
    ExpensesOut,
    IncludeIn,
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


def _check_people(db: Session, trip_id: str, user_ids: list[str],
                  already: frozenset[str] = frozenset()) -> None:
    outsiders = set(user_ids) - _member_ids(db, trip_id) - already
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


def _paid(settlements) -> dict[tuple[str, str], int]:
    out: dict[tuple[str, str], int] = defaultdict(int)
    for s in settlements:
        if s.expense_id:
            out[(s.expense_id, s.from_user_id)] += s.amount_cents
    return out


def _out(e: Expense, blocks: dict[str, tuple[str, int]],
         paid: dict[tuple[str, str], int]) -> ExpenseOut:
    title, day = blocks.get(e.block_id or "", (None, None))
    return ExpenseOut(
        expense_id=e.expense_id, description=e.description, amount_cents=e.amount_cents,
        currency=e.currency, spent_on=e.spent_on, payer_id=e.payer_id,
        block_id=e.block_id, category=e.category, block_title=title, day_index=day,
        shares=[ShareOut(user_id=s.user_id, amount_cents=s.amount_cents,
                         paid_cents=paid.get((e.expense_id, s.user_id), 0))
                for s in sorted(e.shares, key=lambda s: s.user_id)],
    )


def _blocks(db: Session, trip_id: str) -> dict[str, tuple[str | None, int]]:
    """Title and day of every block a cost could name."""
    items = db.scalars(select(ItineraryItem).where(ItineraryItem.trip_id == trip_id))
    return {item.block_id:
            (item.title or (item.place.name if item.place else None), item.day_index)
            for item in items}


def _ledger(db: Session, trip_id: str):
    expenses = db.scalars(
        _live(trip_id).order_by(Expense.spent_on, Expense.created_at)
    ).unique().all()
    shares = db.execute(
        select(ExpenseShare, Expense.currency)
        .join(Expense, Expense.expense_id == ExpenseShare.expense_id)
        .where(Expense.trip_id == trip_id, Expense.deleted.is_(False))
    ).all()
    settlements = db.scalars(
        select(Settlement).where(Settlement.trip_id == trip_id).order_by(Settlement.paid_on)
    ).all()
    return list(expenses), shares, list(settlements)


def overview(db: Session, trip_id: str) -> ExpensesOut:
    """The whole tab. Takes a trip_id rather than a Trip so nothing here imports route_planning."""
    trip = db.get(Trip, trip_id)
    if trip is None:
        raise HTTPException(404, "no such trip")
    expenses, shares, settlements = _ledger(db, trip.trip_id)

    blocks, paid = _blocks(db, trip.trip_id), _paid(settlements)
    return ExpensesOut(
        currency=default_currency(db, trip),
        members=trip_members(db, trip.trip_id),
        expenses=[_out(e, blocks, paid) for e in expenses],
        settlements=[SettlementOut.model_validate(s, from_attributes=True) for s in settlements],
        balances=_balances(expenses, shares, settlements),
    )


def has_balance(db: Session, trip_id: str, user_id: str) -> bool:
    return any(m.user_id == user_id and m.net_cents
               for pile in _balances(*_ledger(db, trip_id)) for m in pile.members)


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
                      currency=body.currency, spent_on=body.spent_on,
                      block_id=body.block_id, category=body.category)
    expense.shares = [ExpenseShare(user_id=u, amount_cents=a) for u, a in amounts.items()]
    db.add(expense)
    db.commit()
    log.info("expense trip=%s %s %d by=%s over=%d",
             trip_id[:8], body.currency, body.amount_cents, body.payer_id[:8], len(amounts))
    return _out(expense, _blocks(db, trip_id), {})


def _includable(db: Session, trip_id: str, user_id: str) -> tuple[list[Expense], set[str]]:
    """Costs split evenly across everyone but this member, with no share of them paid yet."""
    members = _member_ids(db, trip_id)
    if user_id not in members:
        raise HTTPException(404, "not a member of this trip")
    others = members - {user_id}
    linked = set(db.scalars(select(Settlement.expense_id).where(
        Settlement.trip_id == trip_id, Settlement.expense_id.is_not(None))))
    out = []
    for expense in db.scalars(
            _live(trip_id).order_by(Expense.spent_on, Expense.created_at)).unique():
        was = {s.user_id: s.amount_cents for s in expense.shares}
        if expense.expense_id in linked or set(was) != others \
                or was != split_evenly(expense.amount_cents, sorted(was)):
            continue
        out.append(expense)
    return out, others


def includable(db: Session, trip_id: str, user_id: str) -> list[ExpenseOut]:
    blocks = _blocks(db, trip_id)
    return [_out(e, blocks, {}) for e in _includable(db, trip_id, user_id)[0]]


def include_member(db: Session, trip_id: str, user_id: str, body: IncludeIn) -> int:
    chosen = set(body.expense_ids)
    _lock(db, Expense.trip_id == trip_id)
    candidates, others = _includable(db, trip_id, user_id)
    people = sorted(others | {user_id})
    touched = 0
    for expense in candidates:
        if expense.expense_id not in chosen:
            continue
        expense.shares = [ExpenseShare(user_id=u, amount_cents=a)
                          for u, a in split_evenly(expense.amount_cents, people).items()]
        touched += 1

    if touched:
        db.commit()
        log.info("re-split trip=%s with=%s costs=%d", trip_id[:8], user_id[:8], touched)
    return touched


def _lock(db: Session, *where) -> None:
    db.execute(select(Expense.expense_id).where(*where).with_for_update())


def _has_payments(db: Session, expense_id: str) -> bool:
    return db.scalar(select(Settlement.settlement_id)
                     .where(Settlement.expense_id == expense_id).limit(1)) is not None


def _get(db: Session, trip_id: str, expense_id: str) -> Expense:
    expense = db.get(Expense, expense_id)
    if expense is None or expense.trip_id != trip_id or expense.deleted:
        raise HTTPException(404, "no such expense")
    return expense


def edit_expense(db: Session, trip_id: str, expense_id: str, body: ExpenseIn) -> ExpenseOut:
    """Replaces the whole expense including its shares — a correction restates the cost."""
    _lock(db, Expense.expense_id == expense_id)
    expense = _get(db, trip_id, expense_id)
    if (body.payer_id, body.currency) != (expense.payer_id, expense.currency) \
            and _has_payments(db, expense_id):
        raise HTTPException(409, "shares of this cost are paid — undo them before changing who "
                                 "paid it or its currency")
    if body.shares:
        amounts = {s.user_id: s.amount_cents for s in body.shares}
    else:
        amounts = split_evenly(body.amount_cents, sorted(body.participants))
    _check_people(db, trip_id, [body.payer_id, *amounts],
                  frozenset({expense.payer_id, *(s.user_id for s in expense.shares)}))

    expense.payer_id = body.payer_id
    expense.description = body.description.strip()
    expense.amount_cents = body.amount_cents
    expense.currency = body.currency
    expense.spent_on = body.spent_on
    expense.block_id = body.block_id
    expense.category = body.category
    expense.shares = [ExpenseShare(user_id=u, amount_cents=a) for u, a in amounts.items()]
    db.commit()
    paid = _paid(db.scalars(select(Settlement).where(Settlement.expense_id == expense_id)))
    return _out(expense, _blocks(db, trip_id), paid)


def remove_expense(db: Session, trip_id: str, expense_id: str) -> None:
    """Soft, so a balance someone already settled against can still be explained."""
    _lock(db, Expense.expense_id == expense_id)
    expense = _get(db, trip_id, expense_id)
    if _has_payments(db, expense_id):
        raise HTTPException(409, "shares of this cost are paid — undo them before deleting it")
    expense.deleted = True
    db.commit()


def _check_share(db: Session, trip_id: str, body: SettlementIn) -> None:
    _lock(db, Expense.expense_id == body.expense_id)
    expense = _get(db, trip_id, body.expense_id)
    if body.to_user_id != expense.payer_id or body.currency != expense.currency:
        raise HTTPException(422, "a share is paid to whoever paid the cost, in its currency")
    share = next((s.amount_cents for s in expense.shares if s.user_id == body.from_user_id), 0)
    paid = db.scalar(select(func.coalesce(func.sum(Settlement.amount_cents), 0)).where(
        Settlement.expense_id == expense.expense_id,
        Settlement.from_user_id == body.from_user_id))
    if body.amount_cents > share - paid:
        raise HTTPException(409, "that is more than is left of their share")


def add_settlement(db: Session, trip_id: str, body: SettlementIn) -> SettlementOut:
    _check_people(db, trip_id, [body.from_user_id, body.to_user_id])
    if body.expense_id:
        _check_share(db, trip_id, body)
    row = Settlement(settlement_id=str(uuid.uuid4()), trip_id=trip_id,
                     from_user_id=body.from_user_id, to_user_id=body.to_user_id,
                     expense_id=body.expense_id, amount_cents=body.amount_cents,
                     currency=body.currency, paid_on=body.paid_on)
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
