from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import pricing
from .config import get_settings
from .models import Bill, Payment, Subscriber, UsageRecord
from .security import Principal

PHONE_UNIT_MINUTES = 10  # one Add Usage call = 10 minutes of phone
INTERNET_UNIT_MB = 1  # one Add Usage call = 1 MB of internet
CENT = Decimal("0.01")


class ApiError(Exception):
    def __init__(self, http_status: int, code: str, message: str):
        self.http_status = http_status
        self.code = code
        self.message = message
        super().__init__(message)


def _check_period(month: int, year: int) -> None:
    now = datetime.now(timezone.utc)
    if (year, month) > (now.year, now.month):
        raise ApiError(422, "INVALID_PERIOD", f"{year}-{month:02d} is in the future")


def _get_subscriber(db: Session, subscriber_no: str) -> Subscriber:
    sub = db.get(Subscriber, subscriber_no)
    if sub is None:
        raise ApiError(404, "SUBSCRIBER_NOT_FOUND", f"Subscriber {subscriber_no} not found")
    return sub


def _find_bill(db: Session, subscriber_no: str, month: int, year: int, lock=False) -> Bill:
    stmt = select(Bill).where(
        Bill.subscriber_no == subscriber_no, Bill.year == year, Bill.month == month
    )
    if lock:
        stmt = stmt.with_for_update()
    bill = db.scalars(stmt).first()
    if bill is None:
        raise ApiError(
            404,
            "BILL_NOT_FOUND",
            f"No bill calculated for subscriber {subscriber_no} for {year}-{month:02d}",
        )
    return bill


def _status_for(total: Decimal, paid: Decimal) -> str:
    if paid <= 0:
        return "UNPAID" if total > 0 else "PAID"
    return "PAID" if paid >= total else "PARTIALLY_PAID"


def usage_totals(db: Session, subscriber_no: str, month: int, year: int) -> tuple[int, int]:
    rows = db.execute(
        select(UsageRecord.usage_type, func.coalesce(func.sum(UsageRecord.quantity), 0))
        .where(
            UsageRecord.subscriber_no == subscriber_no,
            UsageRecord.year == year,
            UsageRecord.month == month,
        )
        .group_by(UsageRecord.usage_type)
    ).all()
    totals = {t: int(q) for t, q in rows}
    return totals.get("PHONE", 0), totals.get("INTERNET", 0)


# --- Add Usage ---------------------------------------------------------------
def add_usage(db: Session, subscriber_no: str, month: int, year: int, usage_type: str) -> dict:
    _check_period(month, year)
    _get_subscriber(db, subscriber_no)
    qty, unit = (PHONE_UNIT_MINUTES, "MIN") if usage_type == "PHONE" else (INTERNET_UNIT_MB, "MB")
    db.add(
        UsageRecord(
            subscriber_no=subscriber_no, year=year, month=month, usage_type=usage_type, quantity=qty
        )
    )
    db.commit()
    minutes, mb = usage_totals(db, subscriber_no, month, year)
    return {
        "subscriber_no": subscriber_no,
        "month": month,
        "year": year,
        "usage_type": usage_type,
        "added_quantity": qty,
        "unit": unit,
        "period_total": minutes if usage_type == "PHONE" else mb,
    }


# --- Calculate Bill ------------------------------------------------------------
def calculate_bill(db: Session, subscriber_no: str, month: int, year: int) -> Bill:
    _check_period(month, year)
    _get_subscriber(db, subscriber_no)
    minutes, mb = usage_totals(db, subscriber_no, month, year)
    charges = pricing.calculate(minutes, mb)

    bill = db.scalars(
        select(Bill)
        .where(Bill.subscriber_no == subscriber_no, Bill.year == year, Bill.month == month)
        .with_for_update()
    ).first()
    if bill is None:
        bill = Bill(subscriber_no=subscriber_no, year=year, month=month, paid_amount=Decimal("0"))
        db.add(bill)

    # Recalculating keeps every payment already made (paid_amount is never reset).
    bill.phone_minutes = minutes
    bill.internet_mb = mb
    bill.phone_charge = charges.phone_charge
    bill.internet_charge = charges.internet_charge
    bill.total = charges.total
    bill.status = _status_for(charges.total, Decimal(bill.paid_amount))
    bill.calculated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(bill)
    return bill


# --- Query Bill ------------------------------------------------------------------
def bill_summary(bill: Bill) -> dict:
    return {
        "subscriber_no": bill.subscriber_no,
        "month": bill.month,
        "year": bill.year,
        "bill_total": Decimal(bill.total).quantize(CENT),
        "paid_amount": Decimal(bill.paid_amount).quantize(CENT),
        "remaining_balance": bill.remaining_balance.quantize(CENT),
        "currency": bill.currency,
        "status": bill.status,
    }


def query_bill(db: Session, subscriber_no: str, month: int, year: int) -> dict:
    return bill_summary(_find_bill(db, subscriber_no, month, year))


def query_bill_detailed(
    db: Session, subscriber_no: str, month: int, year: int, page: int, page_size: int
) -> dict:
    bill = _find_bill(db, subscriber_no, month, year)
    charges = pricing.calculate(bill.phone_minutes, bill.internet_mb)

    base = select(UsageRecord).where(
        UsageRecord.subscriber_no == subscriber_no,
        UsageRecord.year == year,
        UsageRecord.month == month,
    )
    total_items = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    records = db.scalars(
        base.order_by(UsageRecord.recorded_at, UsageRecord.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    lines = [
        {
            "item": "Phone - included minutes",
            "quantity": Decimal(min(bill.phone_minutes, 1000)),
            "unit": "MIN",
            "amount": Decimal("0.00"),
            "note": "First 1,000 minutes are free",
        },
        {
            "item": "Phone - extra minute blocks",
            "quantity": Decimal(charges.phone_extra_blocks),
            "unit": "BLOCK",
            "amount": charges.phone_charge,
            "note": "$10 per started 1,000-minute block above 1,000 minutes",
        },
        {
            "item": "Internet - base package",
            "quantity": Decimal(1),
            "unit": "PACKAGE",
            "amount": Decimal("50.00"),
            "note": "Covers up to 20 GB (20,000 MB)",
        },
        {
            "item": "Internet - extra data blocks",
            "quantity": Decimal(charges.internet_extra_blocks),
            "unit": "BLOCK",
            "amount": charges.internet_charge - Decimal(get_settings().internet_base_price),
            "note": "$10 per started 10 GB block above 20 GB",
        },
    ]

    for line in lines:
        line["amount"] = Decimal(line["amount"]).quantize(CENT)

    result = bill_summary(bill)
    result.update(
        phone_minutes=bill.phone_minutes,
        internet_mb=bill.internet_mb,
        internet_gb=(Decimal(bill.internet_mb) / 1000).quantize(Decimal("0.001")),
        charges=lines,
        usage_records=[
            {
                "id": r.id,
                "usage_type": r.usage_type,
                "quantity": r.quantity,
                "unit": "MIN" if r.usage_type == "PHONE" else "MB",
                "recorded_at": r.recorded_at,
            }
            for r in records
        ],
        paging={
            "page": page,
            "page_size": page_size,
            "total_items": total_items,
            "total_pages": max(1, -(-total_items // page_size)),
        },
    )
    return result


# --- Pay Bill ------------------------------------------------------------------
def pay_bill(
    db: Session,
    principal: Principal,
    subscriber_no: str,
    month: int,
    year: int,
    amount: Decimal,
    transaction_id: str,
) -> dict:
    amount = Decimal(amount).quantize(CENT)

    if db.scalar(select(Payment.id).where(Payment.transaction_id == transaction_id)):
        raise ApiError(409, "DUPLICATE_TRANSACTION", f"Transaction {transaction_id} was already processed")

    bill = _find_bill(db, subscriber_no, month, year, lock=True)
    remaining = bill.remaining_balance
    if remaining <= 0:
        raise ApiError(409, "BILL_ALREADY_PAID", "This bill has no remaining balance")
    if amount > remaining:
        raise ApiError(
            422,
            "AMOUNT_EXCEEDS_BALANCE",
            f"Amount {amount} exceeds remaining balance {remaining.quantize(CENT)}",
        )

    db.add(Payment(transaction_id=transaction_id, bill_id=bill.id, amount=amount, paid_by=principal.username))
    bill.paid_amount = Decimal(bill.paid_amount) + amount
    bill.status = _status_for(Decimal(bill.total), Decimal(bill.paid_amount))
    try:
        db.commit()
    except IntegrityError:
        # two requests with the same transaction id raced past the first check
        db.rollback()
        raise ApiError(409, "DUPLICATE_TRANSACTION", f"Transaction {transaction_id} was already processed")
    db.refresh(bill)

    return {
        "payment_status": "SUCCESS",
        "transaction_id": transaction_id,
        "paid_amount": amount,
        "total_paid": Decimal(bill.paid_amount).quantize(CENT),
        "remaining_balance": bill.remaining_balance.quantize(CENT),
        "bill_status": bill.status,
    }
