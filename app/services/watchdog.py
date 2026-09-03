import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from app.config import settings
from app.database import db
from app.services.meta_service import meta_service


class ReplyWatchdog:
    """
    Monitors pending n8n bot replies.
    If n8n does not call POST /internal/reply within 60 seconds:
    1. Sends friendly fallback message to the customer.
    2. Logs an error in error_log.
    """
    def __init__(self):
        self.pending_tasks: Dict[str, asyncio.Task] = {}

    def register_inbound_message(
        self,
        wa_id: str,
        conversation_id: int,
        wa_message_id: str,
        inbound_text: str,
    ):
        """Starts 60-second watchdog timer for this message"""
        # Cancel any existing watchdog for the same message ID
        if wa_message_id in self.pending_tasks:
            self.pending_tasks[wa_message_id].cancel()

        task = asyncio.create_task(
            self._timeout_handler(
                wa_id=wa_id,
                conversation_id=conversation_id,
                wa_message_id=wa_message_id,
                inbound_text=inbound_text,
                timeout=settings.WATCHDOG_TIMEOUT_SECONDS,
            )
        )
        self.pending_tasks[wa_message_id] = task

    def resolve_reply(self, wa_message_id: Optional[str], to_wa_id: Optional[str] = None):
        """Cancels watchdog timer when n8n reply callback is received"""
        if wa_message_id and wa_message_id in self.pending_tasks:
            task = self.pending_tasks.pop(wa_message_id)
            if not task.done():
                task.cancel()

    async def _timeout_handler(
        self,
        wa_id: str,
        conversation_id: int,
        wa_message_id: str,
        inbound_text: str,
        timeout: int,
    ):
        try:
            await asyncio.sleep(timeout)

            # If we reached here, n8n timed out!
            print(f"[Watchdog Alert] n8n failed to reply within {timeout}s for message {wa_message_id}")

            # 1. Log error
            db.log_error(
                step="n8n",
                error_text=f"n8n reply watchdog timeout ({timeout}s exceeded)",
                conversation_id=conversation_id,
                wa_id=wa_id,
                inbound_body=inbound_text,
                payload={"wa_message_id": wa_message_id},
            )

            # 2. Deliver fallback message to customer
            fallback_res = await meta_service.send_text_message(
                to_wa_id=wa_id,
                text=settings.FALLBACK_REPLY_TEXT,
            )

            # 3. Log outbound fallback row in messages
            contact = db.upsert_contact(wa_id)
            db.insert_message(
                conversation_id=conversation_id,
                contact_id=contact["id"],
                direction="bot",
                body=settings.FALLBACK_REPLY_TEXT,
                wa_message_id=fallback_res.get("messages", [{}])[0].get("id"),
                meta_status="sent",
            )
        except asyncio.CancelledError:
            # Successfully cancelled because n8n replied in time
            pass
        finally:
            self.pending_tasks.pop(wa_message_id, None)


watchdog = ReplyWatchdog()
