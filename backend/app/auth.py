import os
import hashlib
import hmac
import base64
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

JWT_SECRET = os.getenv("JWT_SECRET", "landwise-dev-secret-change-me")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "43200"))  # 30 days

_bearer = HTTPBearer(auto_error=False)


# ----------------------------------------------------------------------
# Password hashing (PBKDF2-HMAC-SHA256). Avoids a hard dependency on the
# native `bcrypt` wheel while still being a slow, salted, industry-accepted
# KDF suitable for password storage.
# ----------------------------------------------------------------------
_PBKDF2_ITERATIONS = 260_000


def hash_password(password: str) -> str:
    if not password or len(password) < 6:
        raise ValueError("Password must be at least 6 characters long")
    salt = os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(derived).decode()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        scheme, iterations, salt_b64, hash_b64 = stored_hash.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(derived, expected)
    except Exception:
        return False


# ----------------------------------------------------------------------
# JWT access tokens
# ----------------------------------------------------------------------

def create_access_token(user_id: str, email: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired. Please log in again.")
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid authentication token.")


class CurrentUser:
    def __init__(self, user_id: str, email: str):
        self.user_id = user_id
        self.email = email


async def get_current_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)) -> CurrentUser:
    if creds is None or not creds.credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please log in to use LandWise AI.")
    payload = decode_access_token(creds.credentials)
    return CurrentUser(user_id=payload["sub"], email=payload.get("email", ""))


async def get_optional_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)) -> Optional[CurrentUser]:
    if creds is None or not creds.credentials:
        return None
    try:
        payload = decode_access_token(creds.credentials)
        return CurrentUser(user_id=payload["sub"], email=payload.get("email", ""))
    except HTTPException:
        return None

# ----------------------------------------------------------------------
# Email OTP helpers
# ----------------------------------------------------------------------
import secrets

OTP_EXPIRE_MINUTES = int(os.getenv("OTP_EXPIRE_MINUTES", "10"))
OTP_MAX_ATTEMPTS = int(os.getenv("OTP_MAX_ATTEMPTS", "5"))
OTP_HASH_SECRET = os.getenv("OTP_HASH_SECRET", "")


def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(otp: str) -> str:
    if not OTP_HASH_SECRET:
        raise RuntimeError("OTP_HASH_SECRET is not configured.")
    return hmac.new(OTP_HASH_SECRET.encode("utf-8"), otp.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_otp(otp: str, stored_hash: str) -> bool:
    try:
        return hmac.compare_digest(hash_otp(otp), stored_hash or "")
    except Exception:
        return False
