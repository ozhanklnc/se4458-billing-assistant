from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Subscriber(Base):
    __tablename__ = "subscribers"

    subscriber_no: Mapped[str] = mapped_column(String(20), primary_key=True)
    full_name: Mapped[str] = mapped_column(String(100))
    plan_name: Mapped[str] = mapped_column(String(50), default="Standard")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AppUser(Base):
    __tablename__ = "app_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))  # SUBSCRIBER | ADMIN
    subscriber_no: Mapped[str | None] = mapped_column(
        ForeignKey("subscribers.subscriber_no"), nullable=True
    )

    __table_args__ = (CheckConstraint("role in ('SUBSCRIBER','ADMIN')", name="ck_user_role"),)


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subscriber_no: Mapped[str] = mapped_column(ForeignKey("subscribers.subscriber_no"), index=True)
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    usage_type: Mapped[str] = mapped_column(String(10))  # PHONE | INTERNET
    quantity: Mapped[int] = mapped_column(Integer)  # minutes for PHONE, MB for INTERNET
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        CheckConstraint("usage_type in ('PHONE','INTERNET')", name="ck_usage_type"),
        CheckConstraint("quantity > 0", name="ck_usage_qty"),
        CheckConstraint("month between 1 and 12", name="ck_usage_month"),
    )


class Bill(Base):
    __tablename__ = "bills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subscriber_no: Mapped[str] = mapped_column(ForeignKey("subscribers.subscriber_no"))
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    phone_minutes: Mapped[int] = mapped_column(Integer, default=0)
    internet_mb: Mapped[int] = mapped_column(Integer, default=0)
    phone_charge: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    internet_charge: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    status: Mapped[str] = mapped_column(String(20), default="UNPAID")
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    payments: Mapped[list["Payment"]] = relationship(back_populates="bill")

    __table_args__ = (
        UniqueConstraint("subscriber_no", "year", "month", name="uq_bill_period"),
        CheckConstraint("status in ('UNPAID','PARTIALLY_PAID','PAID')", name="ck_bill_status"),
        CheckConstraint("paid_amount >= 0", name="ck_bill_paid"),
    )

    @property
    def remaining_balance(self) -> Decimal:
        return max(Decimal(self.total) - Decimal(self.paid_amount), Decimal("0"))


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_id: Mapped[str] = mapped_column(String(64), unique=True)
    bill_id: Mapped[int] = mapped_column(ForeignKey("bills.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    paid_by: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    bill: Mapped[Bill] = relationship(back_populates="payments")

    __table_args__ = (CheckConstraint("amount > 0", name="ck_payment_amount"),)
