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
    """Admin-only: Creates a new user in Supabase"""
    if user_payload.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privilege required to create users",
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
    if id == 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete primary administrator",
        )

    success = db.delete_user(id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found or could not be deleted",
        )

    return {"message": "User deleted successfully", "success": True}
