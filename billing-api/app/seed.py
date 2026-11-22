"""Create tables and load demo data.

    python -m app.seed            # create tables + insert demo data (idempotent)
    python -m app.seed --reset    # drop everything first

Seed usage rows are daily aggregates written straight to the table, so a month
with 35 GB does not need 35,000 "Add Usage" calls. Bills are produced with the
same calculate_bill() the API uses.
"""
import sys
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from . import services
from .db import Base, SessionLocal, engine
from .models import AppUser, Subscriber, UsageRecord
from .security import Principal, hash_password

SUBSCRIBERS = [
    ("5551001", "Deniz Yilmaz", "Standard"),
    ("5551002", "Ayse Demir", "Standard"),
    ("5551003", "Mehmet Kaya", "Standard"),
]

USERS = [
    ("deniz", "Deniz!2026", "SUBSCRIBER", "5551001"),
    ("ayse", "Ayse!2026", "SUBSCRIBER", "5551002"),
    ("mehmet", "Mehmet!2026", "SUBSCRIBER", "5551003"),
    ("admin", "Admin!2026", "ADMIN", None),
]

# (subscriber, year, month, total phone minutes, total internet MB)
USAGE = [
    ("5551001", 2026, 8, 640, 15_200),
    ("5551001", 2026, 9, 820, 18_400),
    ("5551001", 2026, 10, 1_450, 35_000),  # extra minutes + 2 extra data blocks
    ("5551002", 2026, 9, 1_000, 20_000),  # exactly on both limits
    ("5551002", 2026, 10, 2_300, 12_000),
    ("5551003", 2026, 10, 300, 41_250),
]

# (subscriber, year, month, amount, transaction id)
PAYMENTS = [
    ("5551001", 2026, 8, Decimal("50.00"), "SEED-TX-0001"),
    ("5551001", 2026, 9, Decimal("50.00"), "SEED-TX-0002"),
    ("5551002", 2026, 9, Decimal("50.00"), "SEED-TX-0003"),
    ("5551002", 2026, 10, Decimal("30.00"), "SEED-TX-0004"),
]


def _split(total: int, parts: int, step: int) -> list[int]:
    """Spread a monthly total over `parts` days in multiples of `step`."""
    base = (total // parts) // step * step
    chunks = [base] * parts
    chunks[-1] += total - base * parts
    return [c for c in chunks if c > 0]


def seed() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if db.scalar(select(Subscriber).limit(1)) is not None:
            print("Seed data already present, skipping (use --reset to reload).")
            return

        for no, name, plan in SUBSCRIBERS:
            db.add(Subscriber(subscriber_no=no, full_name=name, plan_name=plan))
        db.flush()
        for username, pwd, role, sub in USERS:
            db.add(AppUser(username=username, password_hash=hash_password(pwd), role=role, subscriber_no=sub))

        for sub, year, month, minutes, mb in USAGE:
            for i, q in enumerate(_split(minutes, 10, 10)):
                db.add(UsageRecord(subscriber_no=sub, year=year, month=month, usage_type="PHONE",
                                   quantity=q, recorded_at=datetime(year, month, 1 + i * 3, 18, tzinfo=timezone.utc)))
            for i, q in enumerate(_split(mb, 14, 1)):
                db.add(UsageRecord(subscriber_no=sub, year=year, month=month, usage_type="INTERNET",
                                   quantity=q, recorded_at=datetime(year, month, 1 + i * 2, 21, tzinfo=timezone.utc)))
        db.commit()

        for sub, year, month, *_ in USAGE:
            services.calculate_bill(db, sub, month, year)

        system = Principal(username="seed", role="ADMIN")
        for sub, year, month, amount, tx in PAYMENTS:
            services.pay_bill(db, system, sub, month, year, amount, tx)

    print("Seed complete.")


if __name__ == "__main__":
    if "--reset" in sys.argv:
        Base.metadata.drop_all(engine)
    seed()
