"""What the sharing endpoints actually do. A trip link grants nothing — access is a user_trips row.

These raise `HTTPException` directly and return response schemas, the same way `route_planning` does.
"""

import logging

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from libs.db import User, UserTrip
from libs.db.enums import TripRole
from tp_api.auth_routes import UserOut
from tp_api.sharing.schemas import MemberIn, MemberOut

log = logging.getLogger("tp_api")

SEARCH_LIMIT = 10


def _member(user: User, role: str) -> MemberOut:
    return MemberOut(user_id=user.user_id, email=user.email, name=user.name,
                     picture=user.picture, role=role)


def search_users(db: Session, me: User, q: str) -> list[UserOut]:
    like = f"%{q.strip()}%"
    users = db.scalars(
        select(User)
        .where(User.user_id != me.user_id, or_(User.email.ilike(like), User.name.ilike(like)))
        .order_by(User.name, User.email)
        .limit(SEARCH_LIMIT)
    ).all()
    return [UserOut.model_validate(u, from_attributes=True) for u in users]


def members(db: Session, trip_id: str) -> list[MemberOut]:
    rows = db.execute(
        select(UserTrip, User)
        .join(User, User.user_id == UserTrip.user_id)
        .where(UserTrip.trip_id == trip_id)
        .order_by(UserTrip.created_at)
    ).all()
    return [_member(u, ut.role) for ut, u in rows]


def add_member(db: Session, trip_id: str, body: MemberIn) -> MemberOut:
    """Share the trip, or change what an existing member may do."""
    user = db.get(User, body.user_id)
    if user is None:
        raise HTTPException(404, "no such user")

    row = db.get(UserTrip, (body.user_id, trip_id))
    if row is None:
        db.add(UserTrip(user_id=body.user_id, trip_id=trip_id, role=body.role))
    elif row.role == TripRole.OWNER:
        raise HTTPException(409, "that is the trip's owner")
    else:
        row.role = body.role
    db.commit()
    log.info("shared trip=%s with=%s as=%s", trip_id[:8], user.email, body.role)
    return _member(user, body.role)


def remove_member(db: Session, trip_id: str, user_id: str, me: User, role: str) -> None:
    """The owner removes anyone; anyone else may only remove themselves."""
    if user_id != me.user_id and role != TripRole.OWNER:
        raise HTTPException(403, "only the trip's owner can remove someone else")

    row = db.get(UserTrip, (user_id, trip_id))
    if row is None:
        raise HTTPException(404, "not a member of this trip")
    if row.role == TripRole.OWNER:
        raise HTTPException(409, "the owner cannot be removed — delete the trip instead")
    db.delete(row)
    db.commit()
    log.info("unshared trip=%s from=%s", trip_id[:8], user_id[:8])
