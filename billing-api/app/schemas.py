from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class UsageType(str, Enum):
    PHONE = "PHONE"
    INTERNET = "INTERNET"


class Period(CamelModel):
    subscriber_no: str = Field(min_length=3, max_length=20, examples=["5551001"])
    month: int = Field(ge=1, le=12, examples=[10])
    year: int = Field(ge=2000, le=2100, examples=[2025])


# --- auth ---------------------------------------------------------------
class LoginRequest(CamelModel):
    username: str
    password: str


class TokenResponse(CamelModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    role: str
    subscriber_no: str | None


# --- usage ----------------------------------------------------------------
class AddUsageRequest(Period):
    usage_type: UsageType = Field(examples=["INTERNET"])


class AddUsageResponse(CamelModel):
    status: str = "SUCCESS"
    subscriber_no: str
    month: int
    year: int
    usage_type: UsageType
    added_quantity: int
    unit: str
    period_total: int


# --- bills ----------------------------------------------------------------
class CalculateBillRequest(Period):
    pass


class TransactionStatus(CamelModel):
    status: str
    message: str
    bill_total: Decimal | None = None


class BillSummary(CamelModel):
    subscriber_no: str
    month: int
    year: int
    bill_total: Decimal
    paid_amount: Decimal
    remaining_balance: Decimal
    currency: str
    status: str


class ChargeLine(CamelModel):
    item: str
    quantity: Decimal
    unit: str
    amount: Decimal
    note: str


class UsageLine(CamelModel):
    id: int
    usage_type: str
    quantity: int
    unit: str
    recorded_at: datetime


class PageInfo(CamelModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int


class BillDetailed(BillSummary):
    phone_minutes: int
    internet_mb: int
    internet_gb: Decimal
    charges: list[ChargeLine]
    usage_records: list[UsageLine]
    paging: PageInfo


# --- payments -------------------------------------------------------------
class PayBillRequest(Period):
    amount: Decimal = Field(gt=0, max_digits=10, decimal_places=2, examples=[25.00])
    transaction_id: str = Field(min_length=6, max_length=64, examples=["TX-2025-10-0001"])


class PayBillResponse(CamelModel):
    payment_status: str
    transaction_id: str
    paid_amount: Decimal
    total_paid: Decimal
    remaining_balance: Decimal
    bill_status: str


class ErrorResponse(CamelModel):
    status: str = "ERROR"
    code: str
    message: str
