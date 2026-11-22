from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import services
from ..db import get_db
from ..models import AppUser
from ..schemas import (
    AddUsageRequest,
    AddUsageResponse,
    BillDetailed,
    BillSummary,
    CalculateBillRequest,
    ErrorResponse,
    LoginRequest,
    PayBillRequest,
    PayBillResponse,
    TokenResponse,
    TransactionStatus,
)
from ..security import (
    Principal,
    create_token,
    current_principal,
    ensure_owner_or_admin,
    require_admin,
    verify_password,
)

router = APIRouter(prefix="/api/v1")

ERR = {
    400: {"model": ErrorResponse},
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}


@router.post("/auth/login", response_model=TokenResponse, tags=["Auth"], responses={401: ERR[401]})
def login(body: LoginRequest, db: Session = Depends(get_db)):
    """Exchange username/password for a JWT (HS256). Demo users are created by `db/seed.py`."""
    user = db.scalars(select(AppUser).where(AppUser.username == body.username)).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise services.ApiError(401, "INVALID_CREDENTIALS", "Username or password is wrong")
    token, expires_in = create_token(user.username, user.role, user.subscriber_no)
    return TokenResponse(
        access_token=token, expires_in=expires_in, role=user.role, subscriber_no=user.subscriber_no
    )


@router.post(
    "/usage",
    response_model=AddUsageResponse,
    status_code=201,
    tags=["Usage"],
    responses=ERR,
    summary="Add Usage (admin)",
)
def add_usage(
    body: AddUsageRequest, db: Session = Depends(get_db), _: Principal = Depends(require_admin)
):
    """PHONE adds 10 minutes, INTERNET adds 1 MB to the given month."""
    return services.add_usage(db, body.subscriber_no, body.month, body.year, body.usage_type.value)


@router.post(
    "/bills/calculate",
    response_model=TransactionStatus,
    tags=["Bills"],
    responses=ERR,
    summary="Calculate Bill (admin)",
)
def calculate_bill(
    body: CalculateBillRequest, db: Session = Depends(get_db), _: Principal = Depends(require_admin)
):
    bill = services.calculate_bill(db, body.subscriber_no, body.month, body.year)
    return TransactionStatus(
        status="SUCCESS",
        message=f"Bill calculated for {body.subscriber_no} {body.year}-{body.month:02d}",
        bill_total=bill.total,
    )


@router.get(
    "/bills",
    response_model=BillSummary,
    tags=["Bills"],
    responses={404: ERR[404], 422: ERR[422]},
    summary="Query Bill (no auth)",
)
def query_bill(
    subscriber_no: str = Query(alias="subscriberNo", min_length=3, max_length=20),
    month: int = Query(ge=1, le=12),
    year: int = Query(ge=2000, le=2100),
    db: Session = Depends(get_db),
):
    return services.query_bill(db, subscriber_no, month, year)


@router.get(
    "/bills/detailed",
    response_model=BillDetailed,
    tags=["Bills"],
    responses=ERR,
    summary="Query Bill Detailed (auth, paged)",
)
def query_bill_detailed(
    subscriber_no: str = Query(alias="subscriberNo", min_length=3, max_length=20),
    month: int = Query(ge=1, le=12),
    year: int = Query(ge=2000, le=2100),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, alias="pageSize", ge=1, le=100),
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    ensure_owner_or_admin(principal, subscriber_no)
    return services.query_bill_detailed(db, subscriber_no, month, year, page, page_size)


@router.post(
    "/payments",
    response_model=PayBillResponse,
    status_code=201,
    tags=["Payments"],
    responses=ERR,
    summary="Pay Bill (auth)",
)
def pay_bill(
    body: PayBillRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    """Simulated payment. Partial payments are allowed; duplicate transaction IDs are rejected."""
    ensure_owner_or_admin(principal, body.subscriber_no)
    return services.pay_bill(
        db, principal, body.subscriber_no, body.month, body.year, body.amount, body.transaction_id
    )
