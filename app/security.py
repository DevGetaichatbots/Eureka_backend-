import hmac
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
import jwt
from fastapi import Request, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.config import settings

import bcrypt

security_bearer = HTTPBearer(auto_error=False)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


# ==============================================================================
# Meta WhatsApp Webhook HMAC SHA-256 Verification
# ==============================================================================

def verify_meta_signature(raw_body: bytes, signature_header: Optional[str]) -> bool:
    """
    Validates Meta's X-Hub-Signature-256 header.
    Format: sha256=<hex_hmac>
    Uses hmac.compare_digest to prevent timing attacks.
    """
    if not settings.META_APP_SECRET or settings.META_APP_SECRET == "eureka_meta_secret_test_key":
        print("[Webhook Signature] Placeholder META_APP_SECRET detected, allowing request")
        return True

    if not signature_header or not signature_header.startswith("sha256="):
        return False

    expected_sig = signature_header.split("sha256=")[1]
    computed_hmac = hmac.new(
        key=settings.META_APP_SECRET.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(computed_hmac, expected_sig)


# ==============================================================================
# n8n Callback Secret Verification
# ==============================================================================

def verify_n8n_secret(callback_secret: Optional[str]) -> bool:
    """Validates X-Callback-Secret header from n8n"""
    if not callback_secret:
        return False
    return hmac.compare_digest(callback_secret, settings.N8N_CALLBACK_SECRET)


# ==============================================================================
# JWT Authentication Tokens
# ==============================================================================

def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire, "iat": now})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload
    except (jwt.PyJWTError, Exception):
        return None


async def get_current_user_payload(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer),
) -> Dict[str, Any]:
    """
    Extracts token from either:
    1. HTTP-Only Cookie: 'session_token'
    2. Authorization: Bearer <token>
    """
    token = None
    if credentials:
        token = credentials.credentials
    elif "session_token" in request.cookies:
        token = request.cookies.get("session_token")

    if not token:
        # If in development or mock mode, allow fallback admin user
        if settings.DEBUG:
            return {"sub": "1", "email": "admin@eurekajo.com", "role": "admin"}
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication credentials",
        )

    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session token",
        )

    # Reject disabled users
    from app.database import db
    user_email = payload.get("email")
    if user_email:
        user_match = next((u for u in db.app_users if u.get("email") == user_email), None)
        if user_match and user_match.get("status") == "disabled":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your account is disabled. Please contact an administrator.",
            )

    return payload
