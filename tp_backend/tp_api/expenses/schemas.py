"""Request and response bodies for the expenses tab.

Every amount is minor units of its own `currency`. Nothing here sums across currencies, so no rate
is ever needed and no rounding is ever argued about.
"""

from datetime import date

from pydantic import BaseModel, Field, field_validator, model_validator

from tp_api.sharing.schemas import MemberOut

Money = Field(gt=0, le=10**12)
CURRENCY = r"^[A-Z]{3}$"


class ShareIn(BaseModel):
    user_id: str = Field(min_length=1, max_length=36)
    amount_cents: int = Field(ge=0, le=10**12)


class ExpenseIn(BaseModel):
    """One cost. `shares` states exact amounts; `participants` splits evenly between them."""

    description: str = Field(min_length=1, max_length=200)
    amount_cents: int = Money
    currency: str = Field(pattern=CURRENCY)
    spent_on: date
    payer_id: str = Field(min_length=1, max_length=36)
    block_id: str | None = Field(default=None, max_length=36)
    category: str | None = Field(default=None, max_length=40)
    participants: list[str] = Field(default_factory=list)
    shares: list[ShareIn] = Field(default_factory=list)

    @field_validator("category", mode="before")
    @classmethod
    def _tidy(cls, v: object) -> object:
        return (" ".join(v.split()) or None) if isinstance(v, str) else v

    @model_validator(mode="after")
    def _one_split(self):
        if bool(self.participants) == bool(self.shares):
            raise ValueError("give either participants to split evenly or exact shares")
        if self.shares and sum(s.amount_cents for s in self.shares) != self.amount_cents:
            raise ValueError("the shares must add up to the amount")
        if len({s.user_id for s in self.shares}) != len(self.shares):
            raise ValueError("one share per person")
        if len(set(self.participants)) != len(self.participants):
            raise ValueError("one share per person")
        return self


class ShareOut(BaseModel):
    user_id: str
    amount_cents: int


class ExpenseOut(BaseModel):
    expense_id: str
    description: str
    amount_cents: int
    currency: str
    spent_on: date
    payer_id: str
    block_id: str | None
    category: str | None
    # What the block is called, when the expense still names one that is on the itinerary.
    block_title: str | None
    day_index: int | None
    shares: list[ShareOut]


class SettlementIn(BaseModel):
    from_user_id: str = Field(min_length=1, max_length=36)
    to_user_id: str = Field(min_length=1, max_length=36)
    amount_cents: int = Money
    currency: str = Field(pattern=CURRENCY)
    paid_on: date

    @model_validator(mode="after")
    def _two_people(self):
        if self.from_user_id == self.to_user_id:
            raise ValueError("a payment needs two people")
        return self


class SettlementOut(BaseModel):
    settlement_id: str
    from_user_id: str
    to_user_id: str
    amount_cents: int
    currency: str
    paid_on: date


class MemberBalance(BaseModel):
    """Positive is owed to them, negative is what they owe. These always sum to zero."""

    user_id: str
    paid_cents: int
    share_cents: int
    # Settlements already paid, signed the same way as the net: without it, paid minus share does
    # not explain the net a settled-up trip reports.
    settled_cents: int
    net_cents: int


class Transfer(BaseModel):
    from_user_id: str
    to_user_id: str
    amount_cents: int


class CurrencyBalance(BaseModel):
    currency: str
    total_cents: int
    members: list[MemberBalance]
    transfers: list[Transfer]


class ExpensesOut(BaseModel):
    """Everything the tab draws, in one call: the trip's people, its costs and who owes whom."""

    currency: str
    members: list[MemberOut]
    expenses: list[ExpenseOut]
    settlements: list[SettlementOut]
    balances: list[CurrencyBalance]
