from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from app.config import settings
from app.database import db


def normalize_wa_id(raw_id: str) -> str:
    """
    Normalizes a WhatsApp ID / phone number to E.164 without the '+' prefix.
    e.g. "+962 79 123-4567" -> "962791234567"
    """
    if not raw_id:
        return ""
    # Strip leading '+' and any non-digit characters
    cleaned = "".join(c for c in str(raw_id) if c.isdigit())
    return cleaned


class ConversationService:
    """
    Manages contact upserting and 24-hour conversation windowing logic
    strictly per Milestone 4 and Section 4 of the Technical Build Document.
    """

    async def upsert_contact(
        self,
        wa_id: str,
        profile_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Upserts a contact by wa_id (E.164 without '+').
        Updates profile_name if provided and bumps last_seen_at.
        """
        clean_wa_id = normalize_wa_id(wa_id)
        return db.upsert_contact(wa_id=clean_wa_id, profile_name=profile_name)

    async def resolve_conversation(
        self,
        contact_id: int,
        current_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Implements 24-hour conversation windowing:
        Finds the contact's most recent conversation.
        If last_message_at is within CONVERSATION_WINDOW_HOURS (default 24h),
        append to it and bump last_message_at + message_count.
        Otherwise, opens a new conversation row.
        """
        return db.resolve_conversation(contact_id=contact_id, now=current_time)


conversation_service = ConversationService()
