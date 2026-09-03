from datetime import datetime, timezone
from typing import Dict, Any, Optional
from app.services.conversation import conversation_service as conv_engine
from app.services.message_log import message_log_service
from app.services.meta_service import meta_service
from app.services.n8n_client import n8n_client
from app.services.watchdog import watchdog
from app.models.schemas import N8NDispatchPayload


class InboundPipelineCoordinator:
    async def handle_inbound_message(
        self,
        wa_id: str,
        profile_name: Optional[str],
        wa_message_id: str,
        message_body: str,
        msg_type: str = "text",
        media_url: Optional[str] = None,
        timestamp_str: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Executes the asynchronous inbound pipeline per Milestones 3, 4 & 5:
        1. Upserts contact by wa_id (E.164 without '+')
        2. Resolves active 24-hour conversation window
        3. Persists customer inbound message
        4. Sends read receipt checkmark to Meta
        5. Dispatches normalized payload to n8n AI workflow
        6. Starts 60-second watchdog timer
        """
        # Green/blue read ticks: notify Meta first, do not wait for n8n
        await meta_service.mark_message_as_read(wa_message_id)

        contact = await conv_engine.upsert_contact(wa_id=wa_id, profile_name=profile_name)

        # 2. Resolve or Open 24h Conversation
        conversation = await conv_engine.resolve_conversation(contact_id=contact["id"])

        # 3. Persist Inbound Message
        inbound_msg = await message_log_service.log_inbound_message(
            conversation_id=conversation["id"],
            contact_id=contact["id"],
            wa_message_id=wa_message_id,
            body=message_body,
            msg_type=msg_type,
            media_url=media_url,
            meta_status="delivered",
        )

        dispatch_payload = N8NDispatchPayload(
            wa_id=wa_id,
            profile_name=contact.get("profile_name"),
            message=message_body,
            message_body=message_body,
            msg_type=msg_type,
            media_url=media_url,
            conversation_id=conversation["id"],
            message_id=wa_message_id,
            wa_message_id=wa_message_id,
            timestamp=timestamp_str or datetime.now(timezone.utc).isoformat(),
        )

        # 6. Start 60s reply watchdog
        watchdog.register_inbound_message(
            wa_id=wa_id,
            conversation_id=conversation["id"],
            wa_message_id=wa_message_id,
            inbound_text=message_body,
        )

        # 7. Dispatch to n8n with 3x exponential backoff
        await n8n_client.dispatch(dispatch_payload, watchdog_instance=watchdog)

        return {
            "contact": contact,
            "conversation": conversation,
            "message": inbound_msg,
        }

    async def handle_bot_reply(
        self,
        to_wa_id: str,
        reply_text: str,
        conversation_id: int,
        reply_to_wa_message_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Executes the outbound bot delivery pipeline:
        1. Resolves watchdog timer
        2. Delivers reply to customer via Meta Cloud API
        3. Persists outbound bot message row
        """
        # 1. Cancel watchdog timer
        watchdog.resolve_reply(reply_to_wa_message_id, to_wa_id)

        # 2. Deliver via Meta Graph API
        meta_res = await meta_service.send_text_message(
            to_wa_id=to_wa_id,
            text=reply_text,
            reply_to_wa_message_id=reply_to_wa_message_id,
        )
        returned_meta_id = meta_res.get("messages", [{}])[0].get("id")

        # 3. Find/upsert contact
        contact = await conv_engine.upsert_contact(wa_id=to_wa_id)

        # 4. Insert Outbound Message
        bot_msg = await message_log_service.log_outbound_message(
            conversation_id=conversation_id,
            contact_id=contact["id"],
            body=reply_text,
            wa_message_id=returned_meta_id,
            msg_type="text",
            meta_status="sent",
        )

        return {
            "status": "delivered",
            "meta_message_id": returned_meta_id,
            "message": bot_msg,
        }


conversation_service = InboundPipelineCoordinator()
