from fastapi import APIRouter, HTTPException, status, Depends
from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel
from app.models.schemas import UserOut, CreateUserRequest, UpdateUserStatusRequest
from app.database import db
from app.security import get_password_hash, get_current_user_payload

router = APIRouter(prefix="/api/users", tags=["Team User Management"])


class UpdateUserRequest(BaseModel):
    status: Optional[str] = None
    role: Optional[str] = None


def is_super_admin(payload: dict) -> bool:
    try:
        uid = int(payload.get("sub", 0))
    except (ValueError, TypeError):
        uid = 0
    email = (payload.get("email") or "").strip().lower()
    return uid == 1 or email == "admin@eurekajo.com"


@router.get("", response_model=List[UserOut])
async def list_users(user_payload: dict = Depends(get_current_user_payload)):
    """Returns all team members directly from Supabase"""
    if user_payload.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privilege required",
        )
    return [
        UserOut(
            id=u["id"],
            email=u["email"],
            role=u["role"],
            status=u["status"],
            created_at=u["created_at"],
            last_login_at=u.get("last_login_at"),
        )
        for u in db.app_users
    ]


@router.post("", response_model=UserOut)
async def create_user(
    req: CreateUserRequest,
    user_payload: dict = Depends(get_current_user_payload),
):
    """Admin-only: Creates a new user in Supabase. Only Super Admin can create other Admins."""
    if user_payload.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privilege required to create users",
        )

    # Only Super Admin can create new Administrator accounts
    if req.role == "admin" and not is_super_admin(user_payload):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the primary Super Administrator can create new Administrator accounts.",
        )

    # Check duplicate
    if any(u["email"].lower() == req.email.lower() for u in db.app_users):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email already exists",
        )

    pwd_hash = get_password_hash(req.password)
    try:
        created = db.create_user(
            email=req.email,
            password_hash=pwd_hash,
            role=req.role,
            status="active",
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )

    if not created.get("id"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="User was not saved to the database",
        )

    return UserOut(
        id=created["id"],
        email=created["email"],
        role=created["role"],
        status=created["status"],
        created_at=created.get("created_at", datetime.now(timezone.utc)),
        last_login_at=None,
    )


@router.patch("/{id}", response_model=UserOut)
@router.put("/{id}", response_model=UserOut)
async def update_user(
    id: int,
    req: UpdateUserRequest,
    user_payload: dict = Depends(get_current_user_payload),
):
    """Updates user status or role in Supabase"""
    if user_payload.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privilege required to update users",
        )

    target_user = next((u for u in db.app_users if u.get("id") == id), None)
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # 1. Super Admin account cannot be modified or demoted
    if id == 1 or (target_user.get("email") or "").lower() == "admin@eurekajo.com":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Primary Super Administrator account cannot be modified or demoted.",
        )

    # 2. Non-Super Admins cannot modify ANY Admin account
    if target_user.get("role") == "admin" and not is_super_admin(user_payload):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the primary Super Administrator can modify other administrator accounts.",
        )

    # 3. Non-Super Admins cannot promote anyone to Admin
    if req.role == "admin" and not is_super_admin(user_payload):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the primary Super Administrator can grant Administrator privileges.",
        )

    update_data = {}
    if req.status is not None:
        update_data["status"] = req.status
    if req.role is not None:
        update_data["role"] = req.role

    updated = db.update_user(id, update_data)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found or update failed",
        )

    return UserOut(
        id=updated["id"],
        email=updated["email"],
        role=updated["role"],
        status=updated["status"],
        created_at=updated["created_at"],
        last_login_at=updated.get("last_login_at"),
    )


@router.patch("/{id}/status", response_model=UserOut)
async def update_user_status(
    id: int,
    req: UpdateUserStatusRequest,
    user_payload: dict = Depends(get_current_user_payload),
):
    """Enables or disables a user account in Supabase"""
    if user_payload.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privilege required to update users",
        )

    target_user = next((u for u in db.app_users if u.get("id") == id), None)
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # 1. Super Admin account cannot be disabled
    if id == 1 or (target_user.get("email") or "").lower() == "admin@eurekajo.com":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Primary Super Administrator account cannot be disabled.",
        )

    # 2. Non-Super Admins cannot disable or enable ANY Admin account
    if target_user.get("role") == "admin" and not is_super_admin(user_payload):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the primary Super Administrator can disable or enable other administrator accounts.",
        )

    updated = db.update_user(id, {"status": req.status})
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return UserOut(
        id=updated["id"],
        email=updated["email"],
        role=updated["role"],
        status=updated["status"],
        created_at=updated["created_at"],
        last_login_at=updated.get("last_login_at"),
    )


@router.delete("/{id}")
async def delete_user(
    id: int,
    user_payload: dict = Depends(get_current_user_payload),
):
    """Deletes a user account from Supabase"""
    if user_payload.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privilege required to delete users",
        )

    target_user = next((u for u in db.app_users if u.get("id") == id), None)
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # 1. Super Admin account cannot be deleted
    if id == 1 or (target_user.get("email") or "").lower() == "admin@eurekajo.com":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete primary Super Administrator account.",
        )

    # 2. Non-Super Admins cannot delete ANY Admin account
    if target_user.get("role") == "admin" and not is_super_admin(user_payload):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the primary Super Administrator can delete administrator accounts.",
        )

    success = db.delete_user(id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found or could not be deleted",
        )

    return {"message": "User deleted successfully", "success": True}

