import hmac
import hashlib
from typing import Optional, Dict, Any, AsyncGenerator
from fastapi import Request, Header, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt

from app.config import settings

security_bearer = HTTPBearer(auto_error=False)


# ==============================================================================
# 1. Database Dependency
# ==============================================================================
async def get_db():
    """
    Database session dependency. Yields an AsyncSession when configured,
    or falls back to the database repository singleton.
    """
    from app.db.session import AsyncSessionLocal
    if AsyncSessionLocal is not None:
        async with AsyncSessionLocal() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()
    else:
        from app.database import db
        yield db


# ==============================================================================
# 2. Authentication Dependency (Milestone 7)
# ==============================================================================
async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer),
) -> Dict[str, Any]:
    """
    Authenticates requests for the Conversation Viewer.
    Accepts:
    - Authorization: Bearer <JWT>
    - Cookie: session_token=<JWT>
    """
    token = None
    if credentials:
        token = credentials.credentials
    elif "session_token" in request.cookies:
        token = request.cookies.get("session_token")

    if not token:
        if settings.DEBUG:
            return {"sub": "1", "email": "admin@eurekajo.com", "role": "admin"}
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    try:
        payload = jwt.decode(
            token,
            settings.SESSION_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
        )


# ==============================================================================
# 3. n8n Shared-Secret Callback Guard (Section 8 & 13)
# ==============================================================================
async def verify_n8n_callback_secret(
    x_callback_secret: Optional[str] = Header(None, alias="X-Callback-Secret"),
) -> str:
    """
    Guards POST /internal/reply using constant-time comparison.
    Rejects with 403 on mismatch.
    """
    if not x_callback_secret:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing X-Callback-Secret header",
        )

    is_valid = hmac.compare_digest(
        x_callback_secret.encode("utf-8"),
        settings.N8N_CALLBACK_SECRET.encode("utf-8"),
    )
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid callback secret",
        )

    return x_callback_secret


# ==============================================================================
# 4. Meta Webhook Signature Guard (Section 13)
# ==============================================================================
def verify_meta_hmac(raw_body: bytes, signature_header: Optional[str]) -> bool:
    """
    Verifies X-Hub-Signature-256 HMAC on raw incoming bytes.
    Uses constant-time comparison to prevent timing side-channel attacks.
    """
    if not signature_header or not signature_header.startswith("sha256="):
        return False

    expected_sig = signature_header.split("sha256=")[1].strip()
    computed_hmac = hmac.new(
        key=settings.META_APP_SECRET.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(computed_hmac, expected_sig)
