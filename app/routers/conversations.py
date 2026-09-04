from fastapi import APIRouter, Query, HTTPException, status, Depends, Body
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from app.models.schemas import (
    ConversationOut,
    ConversationDetailOut,
    ContactOut,
    MessageOut,
    MessageSearchResultOut,
    PaginatedResponse,
)
from app.database import db
from app.security import get_current_user_payload

router = APIRouter(prefix="/api/conversations", tags=["Conversations Viewer"])


@router.get("/messages/search", response_model=List[MessageSearchResultOut])
async def search_messages_endpoint(
    q: str = Query(..., min_length=1),
    limit: int = Query(50, ge=1, le=100),
    user_payload: dict = Depends(get_current_user_payload),
):
    """
    Search messages across all conversations with attached contact info.
    """
    matched_msgs = db.search_messages(q, limit=limit)
    contacts_by_id = {c["id"]: c for c in db.contacts}
    results = []
    for m in matched_msgs:
        contact_dict = contacts_by_id.get(m.get("contact_id"))
        contact_out = (
            ContactOut(
                id=contact_dict["id"],
                wa_id=contact_dict["wa_id"],
                profile_name=contact_dict.get("profile_name"),
                first_seen_at=contact_dict["first_seen_at"],
                last_seen_at=contact_dict["last_seen_at"],
                message_count=contact_dict["message_count"],
            )
            if contact_dict
            else None
        )
        msg_out = MessageOut(
            id=m["id"],
            conversation_id=m.get("conversation_id", 0),
            contact_id=m["contact_id"],
            wa_message_id=m.get("wa_message_id"),
            direction=m["direction"],
            body=m.get("body"),
            msg_type=m.get("msg_type", "text"),
            media_url=m.get("media_url"),
            sent_at=m["sent_at"],
            meta_status=m.get("meta_status", "sent"),
            created_at=m["created_at"],
        )
        results.append(
            MessageSearchResultOut(
                message=msg_out,
                conversation_id=m.get("conversation_id", 0),
                contact=contact_out,
            )
        )
    return results


@router.get("", response_model=PaginatedResponse[ConversationOut])
async def list_conversations(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    window: str = Query("all"),  # 'all' | 'active' | 'archived'
    search: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    date_range: Optional[str] = Query(None),  # 'today' | 'yesterday' | '3' | '7' | '30' | 'custom'
    sort: Optional[str] = Query("newest"),  # 'newest' | 'oldest'
    user_payload: dict = Depends(get_current_user_payload),
):
    """
    Returns paginated list of conversations with attached contact info
    and last message snippet for the inbox feed.
    Supports search, status window, date range filtering, and sorting.
    """
    now = datetime.now(timezone.utc)
    conv_list = []
    contacts_by_id = {c["id"]: c for c in db.contacts}
    latest_by_conv = db.get_latest_messages_map()

    # Timezone-aware date calculations for Asia/Karachi (UTC+5)
    karachi_offset = timezone(timedelta(hours=5))
    today_karachi = datetime.now(karachi_offset).strftime("%Y-%m-%d")
    yesterday_karachi = (datetime.now(karachi_offset) - timedelta(days=1)).strftime("%Y-%m-%d")

    matching_contact_ids = set()
    matching_conv_ids = set()
    if search:
        matching_messages = db.search_messages(search, limit=200)
        for m in matching_messages:
            if m.get("contact_id"):
                matching_contact_ids.add(m["contact_id"])
            if m.get("conversation_id"):
                matching_conv_ids.add(m["conversation_id"])

    for conv in db.conversations:
        contact_dict = contacts_by_id.get(conv["contact_id"])
        if not contact_dict:
            continue

        # Active 24h filter
        delta = now - conv["last_message_at"]
        is_active = delta <= timedelta(hours=24)
        if window == "active" and not is_active:
            continue
        if window == "archived" and is_active:
            continue

        # Date Range Filtering based on latest activity (last_message_at)
        last_dt = conv["last_message_at"]
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        conv_date_str = last_dt.astimezone(karachi_offset).strftime("%Y-%m-%d")

        if date_range == "today" and conv_date_str != today_karachi:
            continue
        elif date_range == "yesterday" and conv_date_str != yesterday_karachi:
            continue
        elif date_range in ("3", "7", "30"):
            num_days = int(date_range)
            cutoff_date = (datetime.now(karachi_offset) - timedelta(days=num_days - 1)).strftime("%Y-%m-%d")
            if conv_date_str < cutoff_date:
                continue
        elif from_date or to_date or date_range == "custom":
            if from_date and conv_date_str < from_date:
                continue
            if to_date and conv_date_str > to_date:
                continue

        # Search filter
        if search:
            q = search.lower()
            name = (contact_dict.get("profile_name") or "").lower()
            wa_id = (contact_dict.get("wa_id") or "").lower()
            is_matched = (
                q in name
                or q in wa_id
                or conv["id"] in matching_conv_ids
                or conv["contact_id"] in matching_contact_ids
            )
            if not is_matched:
                continue

        last_msg = latest_by_conv.get(conv["id"])

        contact_out = ContactOut(
            id=contact_dict["id"],
            wa_id=contact_dict["wa_id"],
            profile_name=contact_dict.get("profile_name"),
            first_seen_at=contact_dict["first_seen_at"],
            last_seen_at=contact_dict["last_seen_at"],
            message_count=contact_dict["message_count"],
        )

        last_msg_out = (
            MessageOut(
                id=last_msg["id"],
                conversation_id=last_msg["conversation_id"],
                contact_id=last_msg["contact_id"],
                wa_message_id=last_msg.get("wa_message_id"),
                direction=last_msg["direction"],
                body=last_msg.get("body"),
                msg_type=last_msg.get("msg_type", "text"),
                media_url=last_msg.get("media_url"),
                sent_at=last_msg["sent_at"],
                meta_status=last_msg.get("meta_status", "sent"),
                created_at=last_msg["created_at"],
            )
            if last_msg
            else None
        )

        conv_list.append(
            ConversationOut(
                id=conv["id"],
                contact_id=conv["contact_id"],
                contact=contact_out,
                started_at=conv["started_at"],
                last_message_at=conv["last_message_at"],
                message_count=conv["message_count"],
                last_message=last_msg_out,
                is_archived=conv.get("is_archived", False),
                archived_at=conv.get("archived_at"),
            )
        )

    # Sort conversations (newest first or oldest first)
    is_reverse = (sort != "oldest")
    conv_list.sort(key=lambda c: c.last_message_at, reverse=is_reverse)

    unique_by_contact: Dict[int, ConversationOut] = {}
    for item in conv_list:
        existing = unique_by_contact.get(item.contact_id)
        if not existing or (item.last_message_at > existing.last_message_at if is_reverse else item.last_message_at < existing.last_message_at):
            unique_by_contact[item.contact_id] = item
    conv_list = list(unique_by_contact.values())
    conv_list.sort(key=lambda c: c.last_message_at, reverse=is_reverse)

    total = len(conv_list)
    start = (page - 1) * limit
    end = start + limit
    paginated_items = conv_list[start:end]
    total_pages = max(1, (total + limit - 1) // limit)

    return PaginatedResponse(
        items=paginated_items,
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages,
    )


@router.get("/{id}", response_model=ConversationDetailOut)
async def get_conversation_detail(
    id: int,
    user_payload: dict = Depends(get_current_user_payload),
):
    """
    Returns full conversation transcript with all messages ordered chronologically.
    """
    conv = db.get_conversation(id)
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation #{id} not found",
        )

    thread_messages = db.get_messages_for_contact(conv["contact_id"])

    messages_out = [
        MessageOut(
            id=m["id"],
            conversation_id=m["conversation_id"],
            contact_id=m["contact_id"],
            wa_message_id=m.get("wa_message_id"),
            direction=m["direction"],
            body=m.get("body"),
            msg_type=m.get("msg_type", "text"),
            media_url=m.get("media_url"),
            sent_at=m["sent_at"],
            meta_status=m.get("meta_status", "sent"),
            created_at=m["created_at"],
        )
        for m in thread_messages
    ]

    active_count = len(messages_out)
    first_active_time = messages_out[0].sent_at if messages_out else conv["started_at"]

    contact_dict = db.get_contact(conv["contact_id"])
    contact_out = None
    if contact_dict:
        # If there are active messages after deletion, reflect the active start timestamp & count
        contact_first_seen = first_active_time if active_count > 0 else contact_dict["first_seen_at"]
        contact_out = ContactOut(
            id=contact_dict["id"],
            wa_id=contact_dict["wa_id"],
            profile_name=contact_dict.get("profile_name"),
            first_seen_at=contact_first_seen,
            last_seen_at=contact_dict["last_seen_at"],
            message_count=active_count if active_count > 0 else contact_dict.get("message_count", 0),
        )

    conv_out = ConversationOut(
        id=conv["id"],
        contact_id=conv["contact_id"],
        contact=contact_out,
        started_at=first_active_time,
        last_message_at=conv["last_message_at"],
        message_count=active_count,
        is_archived=conv.get("is_archived", False),
        archived_at=conv.get("archived_at"),
    )

    return ConversationDetailOut(conversation=conv_out, messages=messages_out)


@router.post("/{id}/archive")
@router.patch("/{id}/archive")
async def toggle_archive_conversation_endpoint(
    id: int,
    payload: Optional[Dict[str, Any]] = None,
    user_payload: dict = Depends(get_current_user_payload),
):
    """
    Archives or unarchives a conversation persistently in Supabase database.
    """
    if user_payload.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privilege required to archive conversations",
        )
    is_archived = True
    chat_user_name = None
    wa_id = None
    archived_by_user = user_payload.get("email") or "admin@eurekajo.com" if isinstance(user_payload, dict) else "admin@eurekajo.com"
    last_message = None
    message_count = 0
    contact_id = None

    if payload:
        if "is_archived" in payload:
            is_archived = bool(payload["is_archived"])
        chat_user_name = payload.get("chat_user_name") or payload.get("contact_name")
        wa_id = payload.get("wa_id")
        if payload.get("archived_by_user"):
            archived_by_user = payload["archived_by_user"]
        last_message = payload.get("last_message")
        message_count = int(payload.get("message_count", 0))
        contact_id = payload.get("contact_id")

    try:
        db.archive_conversation(
            conv_id=id,
            is_archived=is_archived,
            chat_user_name=chat_user_name,
            wa_id=wa_id,
            archived_by_user=archived_by_user,
            last_message=last_message,
            message_count=message_count,
            contact_id=contact_id,
        )
    except Exception as e:
        print(f"Archive error for #{id}: {e}")
    return {"success": True, "id": id, "chat_user_name": chat_user_name, "is_archived": is_archived}


@router.delete("/{id}")
async def delete_conversation_endpoint(
    id: int,
    contact_id: Optional[int] = Query(None),
    wa_id: Optional[str] = Query(None),
    payload: Optional[Dict[str, Any]] = Body(None),
    user_payload: dict = Depends(get_current_user_payload),
):
    """
    Hides/deletes a conversation across all users permanently without hard-deleting messages.
    """
    if user_payload.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privilege required to delete conversations",
        )
    deleted_by_user = user_payload.get("email") or "admin@eurekajo.com" if isinstance(user_payload, dict) else "admin@eurekajo.com"

    if payload:
        if not contact_id and payload.get("contact_id"):
            try:
                contact_id = int(payload["contact_id"])
            except (ValueError, TypeError):
                pass
        if not wa_id and payload.get("wa_id"):
            wa_id = str(payload["wa_id"])
        if payload.get("deleted_by_user"):
            deleted_by_user = payload["deleted_by_user"]

    try:
        db.delete_conversation(
            conv_id=id,
            contact_id=contact_id,
            wa_id=wa_id,
            deleted_by_user=deleted_by_user,
        )
    except Exception as e:
        print(f"Delete conversation error for #{id}: {e}")

    return {"success": True, "id": id}
