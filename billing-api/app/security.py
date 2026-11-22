from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from .config import get_settings

bearer = HTTPBearer(auto_error=False)


class Principal(BaseModel):
    username: str
    role: str
    subscriber_no: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == "ADMIN"


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode()


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode(), hashed.encode())
    except ValueError:
        return False


def create_token(username: str, role: str, subscriber_no: str | None) -> tuple[str, int]:
    s = get_settings()
    expires_in = s.jwt_expire_minutes * 60
    now = datetime.now(timezone.utc)
    payload = {
        "iss": s.jwt_issuer,  # Kong's jwt plugin looks up the credential by this claim
        "sub": username,
        "role": role,
        "subscriberNo": subscriber_no,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256"), expires_in


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def current_principal(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> Principal:
    if creds is None:
        raise _unauthorized("Missing bearer token")
    s = get_settings()
    try:
        data = jwt.decode(
            creds.credentials, s.jwt_secret, algorithms=["HS256"], issuer=s.jwt_issuer
        )
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Token expired")
    except jwt.PyJWTError:
        raise _unauthorized("Invalid token")
    return Principal(username=data["sub"], role=data["role"], subscriber_no=data.get("subscriberNo"))


def require_admin(p: Principal = Depends(current_principal)) -> Principal:
    if not p.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin role required")
    return p


def ensure_owner_or_admin(p: Principal, subscriber_no: str) -> None:
    """A subscriber token may only touch its own subscriber number.

    This is what stops the agent from reading someone else's bill just because a
    different number was typed into the chat.
    """
    if p.is_admin:
        return
    if p.subscriber_no != subscriber_no:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only access your own account")
