from datetime import datetime, timezone
from typing import Optional, Dict, Any
from app.database import db


class MessageLogService:
    """
    Message persistence service responsible for logging inbound customer messages
    and outbound bot replies into the messages table per Milestone 4.
    """

    async def log_inbound_message(
        self,
        conversation_id: int,
        contact_id: int,
        wa_message_id: str,
        body: Optional[str] = None,
        msg_type: str = "text",
        media_url: Optional[str] = None,
        sent_at: Optional[datetime] = None,
        meta_status: str = "delivered",
    ) -> Dict[str, Any]:
        """
        Persists an inbound message sent by a customer.
        Supports text, image, audio, voice notes, documents, and stickers without crashing.
        """
        timestamp = sent_at or datetime.now(timezone.utc)
        clean_body = body if body is not None else f"[{msg_type} message]"

        return db.insert_message(
            conversation_id=conversation_id,
            contact_id=contact_id,
            direction="customer",
            body=clean_body,
            wa_message_id=wa_message_id,
            msg_type=msg_type,
            media_url=media_url,
            sent_at=timestamp,
            meta_status=meta_status,
        )

    async def log_outbound_message(
        self,
        conversation_id: int,
        contact_id: int,
        body: str,
        wa_message_id: Optional[str] = None,
        msg_type: str = "text",
        media_url: Optional[str] = None,
        sent_at: Optional[datetime] = None,
        meta_status: str = "sent",
    ) -> Dict[str, Any]:
        """
        Persists an outbound bot reply with the Meta message ID.
        Every bot reply (including fallback replies) must be visible in the viewer thread.
        """
        timestamp = sent_at or datetime.now(timezone.utc)

        return db.insert_message(
            conversation_id=conversation_id,
            contact_id=contact_id,
            direction="bot",
            body=body,
            wa_message_id=wa_message_id,
            msg_type=msg_type,
            media_url=media_url,
            sent_at=timestamp,
            meta_status=meta_status,
        )


message_log_service = MessageLogService()
