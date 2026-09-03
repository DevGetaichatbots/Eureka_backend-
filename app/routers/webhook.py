import json
from fastapi import APIRouter, Request, Response, BackgroundTasks, HTTPException, status, Query
from app.config import settings
from app.security import verify_meta_signature
from app.database import db
from app.services.conversation_service import conversation_service
from app.services.meta_service import meta_service

router = APIRouter(prefix="/webhook", tags=["Meta WhatsApp Webhook"])


@router.get("/whatsapp")
async def verify_meta_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """
    Meta WhatsApp Cloud API Webhook Handshake Verification.
    Meta requests this when configuring the webhook URL in Meta Developer Dashboard.
    """
    if hub_mode == "subscribe" and hub_verify_token == settings.META_VERIFY_TOKEN:
        print(f"[Webhook Handshake] Successfully verified challenge: {hub_challenge}")
        # Meta expects the plain numeric challenge string as the response body
        return Response(content=hub_challenge, media_type="text/plain", status_code=200)

    print(f"[Webhook Handshake] Rejected verify_token: {hub_verify_token}")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Verification token mismatch",
    )


@router.post("/whatsapp")
async def receive_meta_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
):
    """
    Receives Inbound WhatsApp Webhook events from Meta.
    - Validates X-Hub-Signature-256 HMAC
    - Fast Acknowledgment (<300ms SLA)
    - De-duplicates on wa_message_id (idempotent)
    - Hands off contact upsert & n8n dispatch to background worker
    """
    raw_body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")

    # In production, verify HMAC signature
    if settings.APP_ENV == "production" and not settings.DEBUG:
        if not verify_meta_signature(raw_body, signature):
            db.log_error(
                step="webhook",
                error_text="Invalid Meta X-Hub-Signature-256 signature",
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature",
            )

    try:
        data = json.loads(raw_body.decode("utf-8"))
    except Exception as exc:
        return Response(content="Invalid JSON", status_code=400)

    # Process all entries in the webhook batch
    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            messages = value.get("messages", [])
            contacts = value.get("contacts", [])

            profile_name = None
            if contacts and len(contacts) > 0:
                profile_name = contacts[0].get("profile", {}).get("name")

            for msg in messages:
                wa_message_id = msg.get("id")
                from_wa_id = msg.get("from")
                msg_type = msg.get("type", "text")
                timestamp_str = msg.get("timestamp")

                # De-duplication check (Idempotency)
                if wa_message_id and db.is_message_duplicate(wa_message_id):
                    print(f"[Webhook Idempotency] Skipping already-processed message: {wa_message_id}")
                    continue

                # Extract message body based on type
                message_body = ""
                media_url = None
                if msg_type == "text":
                    message_body = msg.get("text", {}).get("body", "")
                elif msg_type == "image":
                    message_body = msg.get("image", {}).get("caption", "[Photo message]")
                    media_url = msg.get("image", {}).get("id")
                elif msg_type == "audio":
                    message_body = "[Voice Note message]"
                    media_url = msg.get("audio", {}).get("id")
                elif msg_type == "document":
                    message_body = msg.get("document", {}).get("caption", "[Document attachment]")
                    media_url = msg.get("document", {}).get("id")
                else:
                    message_body = f"[{msg_type} attachment]"

                # Mark processed immediately to prevent racing duplicate webhook delivery
                if wa_message_id:
                    db.mark_message_processed(wa_message_id)
                    background_tasks.add_task(
                        meta_service.mark_message_as_read,
                        wa_message_id,
                    )

                background_tasks.add_task(
                    conversation_service.handle_inbound_message,
                    wa_id=from_wa_id,
                    profile_name=profile_name,
                    wa_message_id=wa_message_id,
                    message_body=message_body,
                    msg_type=msg_type,
                    media_url=media_url,
                    timestamp_str=timestamp_str,
                )

    # Return HTTP 200 OK immediately to Meta
    return {"status": "ok"}
