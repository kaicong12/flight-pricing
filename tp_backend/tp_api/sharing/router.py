"""The sharing endpoints. Declaration and validation only — the work is in `service`.

`users_router` is separate because user search is not trip-scoped, so it takes no access gate.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from libs.db import User
from tp_api.auth_routes import UserOut
from tp_api.deps import current_user, db_session, require_admin, require_trip_access
from tp_api.sharing import service
from tp_api.sharing.schemas import MemberIn, MemberOut

router = APIRouter(dependencies=[Depends(require_trip_access)], tags=["sharing"])
users_router = APIRouter(tags=["sharing"])

Db = Annotated[Session, Depends(db_session)]
Me = Annotated[User, Depends(current_user)]
Role = Annotated[str, Depends(require_trip_access)]


@users_router.get("/users/search", response_model=list[UserOut])
def search_users(db: Db, me: Me, q: Annotated[str, Query(min_length=2, max_length=120)],
                 ) -> list[UserOut]:
    """Who you could share with. Signed-in only, and never yourself."""
    return service.search_users(db, me, q)


@router.get("/trips/{trip_id}/members", response_model=list[MemberOut])
def list_members(trip_id: str, db: Db) -> list[MemberOut]:
    return service.members(db, trip_id)


@router.post("/trips/{trip_id}/members", response_model=MemberOut,
             dependencies=[Depends(require_admin)])
def add_member(trip_id: str, body: MemberIn, db: Db) -> MemberOut:
    return service.add_member(db, trip_id, body)


@router.delete("/trips/{trip_id}/members/{user_id}", status_code=204)
def remove_member(trip_id: str, user_id: str, db: Db, me: Me, role: Role) -> None:
    service.remove_member(db, trip_id, user_id, me, role)
