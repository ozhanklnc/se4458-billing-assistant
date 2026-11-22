"""One or more success tests and failure/edge tests per API operation."""
from datetime import datetime, timezone

import jwt

from app.config import get_settings

V1 = "/api/v1"


def period(**extra):
    return {"subscriberNo": "5551001", "month": 10, "year": 2025, **extra}


# ---------------------------------------------------------------- auth
class TestLogin:
    def test_login_success_returns_jwt_with_subscriber_claim(self, client):
        r = client.post(f"{V1}/auth/login", json={"username": "u1", "password": "pw1-secret"})
        assert r.status_code == 200
        body = r.json()
        claims = jwt.decode(body["accessToken"], get_settings().jwt_secret, algorithms=["HS256"])
        assert claims["subscriberNo"] == "5551001"
        assert claims["iss"] == "billing-api"
        assert body["role"] == "SUBSCRIBER"

    def test_login_wrong_password(self, client):
        r = client.post(f"{V1}/auth/login", json={"username": "u1", "password": "nope"})
        assert r.status_code == 401
        assert r.json()["code"] == "INVALID_CREDENTIALS"


# ---------------------------------------------------------------- add usage
class TestAddUsage:
    def test_phone_adds_10_minutes(self, client, admin_headers):
        r = client.post(f"{V1}/usage", json=period(usageType="PHONE"), headers=admin_headers)
        assert r.status_code == 201
        assert r.json()["addedQuantity"] == 10
        assert r.json()["unit"] == "MIN"
        r = client.post(f"{V1}/usage", json=period(usageType="PHONE"), headers=admin_headers)
        assert r.json()["periodTotal"] == 20

    def test_internet_adds_1_mb(self, client, admin_headers):
        r = client.post(f"{V1}/usage", json=period(usageType="INTERNET"), headers=admin_headers)
        assert r.status_code == 201
        assert (r.json()["addedQuantity"], r.json()["unit"]) == (1, "MB")

    def test_requires_token(self, client):
        r = client.post(f"{V1}/usage", json=period(usageType="PHONE"))
        assert r.status_code == 401

    def test_subscriber_token_is_not_enough(self, client, user_headers):
        r = client.post(f"{V1}/usage", json=period(usageType="PHONE"), headers=user_headers)
        assert r.status_code == 403

    def test_invalid_usage_type(self, client, admin_headers):
        r = client.post(f"{V1}/usage", json=period(usageType="SMS"), headers=admin_headers)
        assert r.status_code == 422
        assert r.json()["code"] == "VALIDATION_ERROR"

    def test_unknown_subscriber(self, client, admin_headers):
        body = period(usageType="PHONE", subscriberNo="9999999")
        r = client.post(f"{V1}/usage", json=body, headers=admin_headers)
        assert r.status_code == 404
        assert r.json()["code"] == "SUBSCRIBER_NOT_FOUND"

    def test_future_period_rejected(self, client, admin_headers):
        body = period(usageType="PHONE", year=datetime.now(timezone.utc).year + 1)
        r = client.post(f"{V1}/usage", json=body, headers=admin_headers)
        assert r.status_code == 422
        assert r.json()["code"] == "INVALID_PERIOD"


# ---------------------------------------------------------------- calculate bill
class TestCalculateBill:
    def test_calculates_from_usage(self, client, admin_headers, october_bill):
        r = client.post(f"{V1}/bills/calculate", json=period(), headers=admin_headers)
        assert r.status_code == 200
        assert r.json()["status"] == "SUCCESS"
        assert float(r.json()["billTotal"]) == 80.0

    def test_month_without_usage_is_base_package_only(self, client, admin_headers):
        r = client.post(f"{V1}/bills/calculate", json=period(month=3), headers=admin_headers)
        assert float(r.json()["billTotal"]) == 50.0

    def test_recalculation_keeps_existing_payments(self, client, admin_headers, user_headers, october_bill):
        client.post(f"{V1}/payments", json=period(amount=30, transactionId="TX-KEEP-1"), headers=user_headers)
        for _ in range(3):  # 30 more minutes, still within the same block
            client.post(f"{V1}/usage", json=period(usageType="PHONE"), headers=admin_headers)
        client.post(f"{V1}/bills/calculate", json=period(), headers=admin_headers)
        bill = client.get(f"{V1}/bills", params=period()).json()
        assert float(bill["paidAmount"]) == 30.0
        assert float(bill["remainingBalance"]) == 50.0
        assert bill["status"] == "PARTIALLY_PAID"

    def test_requires_admin(self, client, user_headers):
        r = client.post(f"{V1}/bills/calculate", json=period(), headers=user_headers)
        assert r.status_code == 403

    def test_invalid_month(self, client, admin_headers):
        r = client.post(f"{V1}/bills/calculate", json=period(month=13), headers=admin_headers)
        assert r.status_code == 422


# ---------------------------------------------------------------- query bill
class TestQueryBill:
    def test_returns_summary_without_auth(self, client, october_bill):
        r = client.get(f"{V1}/bills", params=period())
        assert r.status_code == 200
        b = r.json()
        assert float(b["billTotal"]) == 80.0
        assert float(b["paidAmount"]) == 0.0
        assert float(b["remainingBalance"]) == 80.0
        assert b["status"] == "UNPAID"

    def test_bill_not_found(self, client):
        r = client.get(f"{V1}/bills", params=period(month=1))
        assert r.status_code == 404
        assert r.json()["code"] == "BILL_NOT_FOUND"

    def test_missing_parameter(self, client):
        r = client.get(f"{V1}/bills", params={"subscriberNo": "5551001", "month": 10})
        assert r.status_code == 422


# ---------------------------------------------------------------- query bill detailed
class TestQueryBillDetailed:
    def test_owner_gets_breakdown(self, client, user_headers, october_bill):
        r = client.get(f"{V1}/bills/detailed", params=period(), headers=user_headers)
        assert r.status_code == 200
        d = r.json()
        assert d["phoneMinutes"] == 1450
        assert float(d["internetGb"]) == 35.0
        extra_data = next(c for c in d["charges"] if c["item"] == "Internet - extra data blocks")
        assert float(extra_data["quantity"]) == 2
        assert float(extra_data["amount"]) == 20.0

    def test_paging(self, client, user_headers, october_bill):
        r = client.get(f"{V1}/bills/detailed", params=period(page=2, pageSize=1), headers=user_headers)
        d = r.json()
        assert d["paging"] == {"page": 2, "pageSize": 1, "totalItems": 2, "totalPages": 2}
        assert len(d["usageRecords"]) == 1

    def test_requires_token(self, client, october_bill):
        assert client.get(f"{V1}/bills/detailed", params=period()).status_code == 401

    def test_other_subscriber_is_forbidden(self, client, other_user_headers, october_bill):
        r = client.get(f"{V1}/bills/detailed", params=period(), headers=other_user_headers)
        assert r.status_code == 403
        assert r.json()["code"] == "FORBIDDEN"

    def test_page_size_limit(self, client, user_headers, october_bill):
        r = client.get(f"{V1}/bills/detailed", params=period(pageSize=500), headers=user_headers)
        assert r.status_code == 422

    def test_expired_token(self, client, october_bill):
        s = get_settings()
        token = jwt.encode(
            {"iss": s.jwt_issuer, "sub": "u1", "role": "SUBSCRIBER", "subscriberNo": "5551001", "exp": 1},
            s.jwt_secret, algorithm="HS256",
        )
        r = client.get(f"{V1}/bills/detailed", params=period(), headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401
        assert "expired" in r.json()["message"].lower()


# ---------------------------------------------------------------- pay bill
class TestPayBill:
    def test_partial_then_full_payment(self, client, user_headers, october_bill):
        r = client.post(f"{V1}/payments", json=period(amount=30, transactionId="TX-0001"), headers=user_headers)
        assert r.status_code == 201
        assert r.json()["billStatus"] == "PARTIALLY_PAID"
        assert float(r.json()["remainingBalance"]) == 50.0

        r = client.post(f"{V1}/payments", json=period(amount=50, transactionId="TX-0002"), headers=user_headers)
        assert r.json()["billStatus"] == "PAID"
        assert float(r.json()["remainingBalance"]) == 0.0

    def test_duplicate_transaction_rejected_and_balance_unchanged(self, client, user_headers, october_bill):
        body = period(amount=10, transactionId="TX-DUP-01")
        assert client.post(f"{V1}/payments", json=body, headers=user_headers).status_code == 201
        r = client.post(f"{V1}/payments", json=body, headers=user_headers)
        assert r.status_code == 409
        assert r.json()["code"] == "DUPLICATE_TRANSACTION"
        assert float(client.get(f"{V1}/bills", params=period()).json()["paidAmount"]) == 10.0

    def test_amount_exceeding_balance(self, client, user_headers, october_bill):
        r = client.post(f"{V1}/payments", json=period(amount=80.01, transactionId="TX-BIG-01"), headers=user_headers)
        assert r.status_code == 422
        assert r.json()["code"] == "AMOUNT_EXCEEDS_BALANCE"

    def test_paid_bill_cannot_be_paid_again(self, client, user_headers, october_bill):
        client.post(f"{V1}/payments", json=period(amount=80, transactionId="TX-FULL-1"), headers=user_headers)
        r = client.post(f"{V1}/payments", json=period(amount=1, transactionId="TX-FULL-2"), headers=user_headers)
        assert r.status_code == 409
        assert r.json()["code"] == "BILL_ALREADY_PAID"

    def test_zero_or_negative_amount(self, client, user_headers, october_bill):
        r = client.post(f"{V1}/payments", json=period(amount=0, transactionId="TX-ZERO-1"), headers=user_headers)
        assert r.status_code == 422

    def test_cannot_pay_someone_elses_bill(self, client, other_user_headers, october_bill):
        r = client.post(f"{V1}/payments", json=period(amount=10, transactionId="TX-OTHER1"), headers=other_user_headers)
        assert r.status_code == 403

    def test_requires_token(self, client, october_bill):
        r = client.post(f"{V1}/payments", json=period(amount=10, transactionId="TX-NOAUTH"))
        assert r.status_code == 401

    def test_bill_not_calculated(self, client, user_headers):
        r = client.post(f"{V1}/payments", json=period(month=2, amount=10, transactionId="TX-NOBILL"), headers=user_headers)
        assert r.status_code == 404


# ---------------------------------------------------------------- gateway-only access
class TestGatewaySecret:
    def test_direct_call_without_gateway_header_is_rejected(self, client, october_bill, monkeypatch):
        monkeypatch.setattr(get_settings(), "gateway_secret", "s3cret-from-kong")
        r = client.get(f"{V1}/bills", params=period())
        assert r.status_code == 403
        assert r.json()["code"] == "DIRECT_ACCESS_FORBIDDEN"

    def test_call_with_gateway_header_passes(self, client, october_bill, monkeypatch):
        monkeypatch.setattr(get_settings(), "gateway_secret", "s3cret-from-kong")
        r = client.get(f"{V1}/bills", params=period(), headers={"X-Gateway-Secret": "s3cret-from-kong"})
        assert r.status_code == 200

    def test_health_stays_open_for_probes(self, client, monkeypatch):
        monkeypatch.setattr(get_settings(), "gateway_secret", "s3cret-from-kong")
        assert client.get("/health").status_code == 200
