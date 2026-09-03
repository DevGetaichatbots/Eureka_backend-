from fastapi import APIRouter, Query, Depends
from typing import Optional
from app.models.schemas import ErrorLogOut, PaginatedResponse
from app.database import db
from app.security import get_current_user_payload

router = APIRouter(prefix="/api/errors", tags=["Diagnostic Error Logs"])


@router.get("", response_model=PaginatedResponse[ErrorLogOut])
async def list_error_logs(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    step: Optional[str] = Query(None),
    user_payload: dict = Depends(get_current_user_payload),
):
    """
    Returns paginated diagnostic error logs for system monitoring.
    """
    filtered_logs = db.error_logs
    if step and step != "all":
        filtered_logs = [err for err in filtered_logs if err["step"] == step]

    sorted_logs = sorted(filtered_logs, key=lambda x: x["created_at"], reverse=True)

    total = len(sorted_logs)
    start_idx = (page - 1) * limit
    paged = sorted_logs[start_idx : start_idx + limit]

    items_out = [
        ErrorLogOut(
            id=err["id"],
            conversation_id=err.get("conversation_id"),
            wa_id=err.get("wa_id"),
            inbound_body=err.get("inbound_body"),
            step=err["step"],
            error_text=err["error_text"],
            payload=err.get("payload"),
            created_at=err["created_at"],
        )
        for err in paged
    ]

    return PaginatedResponse(
        items=items_out,
        total=total,
        page=page,
        limit=limit,
        total_pages=max(1, (total + limit - 1) // limit),
    )
