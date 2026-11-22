"""Test setup.

By default the tests run against an in-memory SQLite database so they work on any
machine with no services running. Set TEST_DATABASE_URL to run the same tests
against PostgreSQL, e.g.

    TEST_DATABASE_URL=postgresql+psycopg://billing:billing@localhost:5432/billing_test pytest
"""
import os
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import AppUser, Bill, Subscriber, UsageRecord
from app.security import create_token, hash_password

TEST_DB = os.getenv("TEST_DATABASE_URL", "sqlite://")

if TEST_DB.startswith("sqlite"):
    engine = create_engine(TEST_DB, connect_args={"check_same_thread": False}, poolclass=StaticPool)
else:
    engine = create_engine(TEST_DB)
TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = TestingSession()
    session.add_all([
        Subscriber(subscriber_no="5551001", full_name="Test One"),
        Subscriber(subscriber_no="5551002", full_name="Test Two"),
    ])
    session.flush()
    session.add_all([
        AppUser(username="u1", password_hash=hash_password("pw1-secret"), role="SUBSCRIBER", subscriber_no="5551001"),
        AppUser(username="admin", password_hash=hash_password("admin-secret"), role="ADMIN"),
    ])
    session.commit()
    yield session
    session.close()


@pytest.fixture()
def client(db):
    def _get_db():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def admin_headers():
    return _auth(create_token("admin", "ADMIN", None)[0])


@pytest.fixture()
def user_headers():
    return _auth(create_token("u1", "SUBSCRIBER", "5551001")[0])


@pytest.fixture()
def other_user_headers():
    return _auth(create_token("u2", "SUBSCRIBER", "5551002")[0])


@pytest.fixture()
def october_bill(db):
    """5551001, 2025-10: 1,450 min and 35,000 MB -> $10 phone + $70 internet = $80."""
    db.add_all([
        UsageRecord(subscriber_no="5551001", year=2025, month=10, usage_type="PHONE", quantity=1450),
        UsageRecord(subscriber_no="5551001", year=2025, month=10, usage_type="INTERNET", quantity=35000),
    ])
    bill = Bill(
        subscriber_no="5551001", year=2025, month=10, phone_minutes=1450, internet_mb=35000,
        phone_charge=Decimal("10"), internet_charge=Decimal("70"), total=Decimal("80"),
        paid_amount=Decimal("0"), status="UNPAID",
    )
    db.add(bill)
    db.commit()
    return bill
