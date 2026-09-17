"""Request and response bodies for members and user search."""

from pydantic import BaseModel, Field

from libs.db.enums import TripRole
from tp_api.auth_routes import UserOut


class MemberOut(UserOut):
    role: str


class MemberIn(BaseModel):
    """No owner: ownership is not something a request can hand out."""

    user_id: str = Field(min_length=1, max_length=36)
    role: str = Field(default=TripRole.EDITOR,
                      pattern=f"^({TripRole.EDITOR}|{TripRole.VIEWER})$")
