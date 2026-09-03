from fastapi import APIRouter, Response, HTTPException, status, Depends
from datetime import datetime, timezone
from app.models.schemas import LoginRequest, LoginResponse, UserOut, ChangePasswordRequest
from app.security import verify_password, get_password_hash, create_access_token, get_current_user_payload
from app.database import db

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.post("/login", response_model=LoginResponse)
async def login(credentials: LoginRequest, response: Response):
    """
    Authenticates conversation viewer and admin users.
    Sets secure HTTP-Only cookie 'session_token'.
    """
    user_match = None
    for u in db.app_users:
        if u["email"].lower() == credentials.email.lower():
            user_match = u
            break

    # Strict bcrypt-only verification — no hardcoded bypasses
    valid = False
    if user_match and user_match.get("password_hash"):
        valid = verify_password(credentials.password, user_match["password_hash"])

    if not valid or not user_match or user_match.get("status") == "disabled":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    # Update last login in memory AND persist to Supabase
    now_utc = datetime.now(timezone.utc)
    user_match["last_login_at"] = now_utc
    db.update_last_login(user_match["id"])

    # Create JWT Token
    token = create_access_token({
        "sub": str(user_match["id"]),
        "email": user_match["email"],
        "role": user_match["role"],
    })

    # Set HTTP-only cookie
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=86400,
    )

    user_out = UserOut(
        id=user_match["id"],
        email=user_match["email"],
        role=user_match["role"],
        status=user_match["status"],
        created_at=user_match["created_at"],
        last_login_at=user_match["last_login_at"],
    )

    return LoginResponse(
        success=True,
        user=user_out,
        token=token,
        message="Authentication successful",
    )


@router.post("/logout")
async def logout(response: Response):
    """Clears the session cookie"""
    response.delete_cookie(key="session_token")
    return {"message": "Successfully logged out"}


@router.get("/me")
async def get_me(user_payload: dict = Depends(get_current_user_payload)):
    """Returns profile for currently authenticated viewer session"""
    email = user_payload.get("email", "admin@eurekajo.com")
    user_match = next((u for u in db.app_users if u["email"] == email), None)

    if not user_match:
        user_match = {
            "id": 1,
            "email": email,
            "role": user_payload.get("role", "admin"),
            "status": "active",
            "created_at": datetime.now(timezone.utc),
            "last_login_at": datetime.now(timezone.utc),
        }

    return {
        "user": UserOut(
            id=user_match["id"],
            email=user_match["email"],
            role=user_match["role"],
            status=user_match["status"],
            created_at=user_match["created_at"],
            last_login_at=user_match.get("last_login_at"),
        )
    }


@router.post("/change-password")
async def change_password(
    req: ChangePasswordRequest,
    user_payload: dict = Depends(get_current_user_payload),
):
    """Allows authenticated user to update their own password — bcrypt only."""
    email = user_payload.get("email")
    user_id = int(user_payload.get("sub", 0)) if user_payload.get("sub") else None

    user_match = None
    for u in db.app_users:
        if (user_id and u.get("id") == user_id) or (email and u.get("email", "").lower() == email.lower()):
            user_match = u
            break

    if not user_match:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User account not found",
        )

    # Strict bcrypt-only verification — no hardcoded bypasses
    if not user_match.get("password_hash") or not verify_password(req.current_password, user_match["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    if len(req.new_password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be at least 6 characters long",
        )

    if req.new_password == req.current_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from current password",
        )

    new_hash = get_password_hash(req.new_password)
    user_match["password_hash"] = new_hash
    db.update_user_password(user_match["id"], new_hash)

    return {"success": True, "message": "Password updated successfully"}
