import hmac
from fastapi import APIRouter, Header, HTTPException, status
from app.config import settings
from app.models.schemas import N8NReplyCallback
from app.services.conversation_service import conversation_service
from app.services.meta_service import meta_service
from app.services.message_log import message_log_service
from app.services.conversation import conversation_service as conv_engine
from app.services.watchdog import watchdog
from app.database import db

router = APIRouter(prefix="/internal", tags=["Internal Bot Callbacks"])


def verify_secret_constant_time(secret_header: str) -> bool:
    """
    Validates X-Callback-Secret using constant-time comparison to prevent timing attacks.
    """
    if not secret_header or not settings.N8N_CALLBACK_SECRET:
        return False
    return hmac.compare_digest(secret_header.strip(), settings.N8N_CALLBACK_SECRET.strip())


@router.post("/reply")
async def receive_n8n_reply(
    payload: N8NReplyCallback,
    x_callback_secret: str = Header(None, alias="X-Callback-Secret"),
):
    """
    Protected internal endpoint called by n8n per Milestone 5 & Section 9:
    - Guarded by X-Callback-Secret (reject 403 on mismatch)
    - If status == 'error': logs to error_log (step='n8n') and sends fallback message
    - If status == 'ok': sends text to customer via Meta Cloud API and logs outbound row
    - Resolves and cancels the 60-second watchdog timer
    """
    wa_id = payload.resolved_wa_id
    reply_text = payload.resolved_text

    # 1. Constant-time authentication check
    if not verify_secret_constant_time(x_callback_secret):
        db.log_error(
            step="n8n",
            error_text="Unauthorized access to POST /internal/reply: invalid X-Callback-Secret",
            conversation_id=payload.conversation_id,
            wa_id=wa_id,
            inbound_body=reply_text,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Invalid callback secret",
        )

    # 2. Resolve/cancel watchdog
    watchdog.resolve_reply(payload.reply_to_wa_message_id, wa_id)

    # 3. Handle status == 'error' from n8n
    if payload.status == "error":
        error_msg = payload.error_message or "n8n reported an error in workflow execution"
        print(f"[Internal Reply] n8n reported error for {wa_id}: {error_msg}")

        # Log to error_log (step='n8n')
        db.log_error(
            step="n8n",
            error_text=error_msg,
            conversation_id=payload.conversation_id,
            wa_id=wa_id,
            inbound_body=reply_text,
        )

        # Deliver fallback message instead of empty/error text
        delivery_res = await meta_service.send_text_message(
            to_wa_id=wa_id,
            text=settings.FALLBACK_REPLY_TEXT,
            reply_to_wa_message_id=payload.reply_to_wa_message_id,
        )
        meta_id = delivery_res.get("messages", [{}])[0].get("id")

        # Log fallback message in database
        contact = await conv_engine.upsert_contact(wa_id)
        bot_msg = await message_log_service.log_outbound_message(
            conversation_id=payload.conversation_id,
            contact_id=contact["id"],
            body=settings.FALLBACK_REPLY_TEXT,
            wa_message_id=meta_id,
            msg_type="text",
            meta_status="sent",
        )
        return {
            "status": "error_handled_with_fallback",
            "meta_message_id": meta_id,
            "message": bot_msg,
        }

    # 4. Handle status == 'ok': deliver bot reply
    try:
        delivery_res = await meta_service.send_text_message(
            to_wa_id=wa_id,
            text=reply_text,
            reply_to_wa_message_id=payload.reply_to_wa_message_id,
        )
        meta_id = delivery_res.get("messages", [{}])[0].get("id")

        # Persist outbound bot message
        contact = await conv_engine.upsert_contact(wa_id)
        bot_msg = await message_log_service.log_outbound_message(
            conversation_id=payload.conversation_id,
            contact_id=contact["id"],
            body=reply_text,
            wa_message_id=meta_id,
            msg_type="text",
            meta_status="sent",
        )
        return {
            "status": "delivered",
            "meta_message_id": meta_id,
            "message": bot_msg,
        }
    except Exception as exc:
        db.log_error(
            step="meta_send",
            error_text=f"Failed delivering reply to Meta: {str(exc)}",
            conversation_id=payload.conversation_id,
            wa_id=wa_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed delivering bot reply: {str(exc)}",
        )
