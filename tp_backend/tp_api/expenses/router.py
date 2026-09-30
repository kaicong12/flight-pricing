"""The expenses endpoints. Declaration and validation only — the work is in `service`.

One GET returns the whole tab, because a balance is only meaningful beside the costs it came from.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from tp_api.deps import db_session, require_edit, require_trip_access
from tp_api.expenses import service
from tp_api.expenses.schemas import ExpenseIn, ExpenseOut, ExpensesOut, SettlementIn, SettlementOut

router = APIRouter(dependencies=[Depends(require_trip_access)], tags=["expenses"])
Edit = [Depends(require_edit)]

Db = Annotated[Session, Depends(db_session)]


@router.get("/trips/{trip_id}/expenses", response_model=ExpensesOut)
def overview(trip_id: str, db: Db) -> ExpensesOut:
    return service.overview(db, trip_id)


@router.post("/trips/{trip_id}/expenses", response_model=ExpenseOut, dependencies=Edit)
def add_expense(trip_id: str, body: ExpenseIn, db: Db) -> ExpenseOut:
    return service.add_expense(db, trip_id, body)


@router.put("/trips/{trip_id}/expenses/{expense_id}", response_model=ExpenseOut, dependencies=Edit)
def edit_expense(trip_id: str, expense_id: str, body: ExpenseIn, db: Db) -> ExpenseOut:
    return service.edit_expense(db, trip_id, expense_id, body)


@router.delete("/trips/{trip_id}/expenses/{expense_id}", status_code=204, dependencies=Edit)
def remove_expense(trip_id: str, expense_id: str, db: Db) -> None:
    service.remove_expense(db, trip_id, expense_id)


@router.post("/trips/{trip_id}/settlements", response_model=SettlementOut, dependencies=Edit)
def add_settlement(trip_id: str, body: SettlementIn, db: Db) -> SettlementOut:
    return service.add_settlement(db, trip_id, body)


@router.delete("/trips/{trip_id}/settlements/{settlement_id}", status_code=204, dependencies=Edit)
def remove_settlement(trip_id: str, settlement_id: str, db: Db) -> None:
    service.remove_settlement(db, trip_id, settlement_id)
