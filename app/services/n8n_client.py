import asyncio
import httpx
from typing import Dict, Any, Optional
from app.config import settings
from app.database import db
from app.models.schemas import N8NDispatchPayload
from app.services.meta_service import meta_service
from app.services.message_log import message_log_service


class N8NClient:
    """
    Client for n8n AI workflow integration per Milestone 5.
    - Sends normalized inbound payload to N8N_WEBHOOK_URL
    - Retries 3x with exponential backoff (2s, 4s, 8s) on failure
    - Logs errors to error_log (step='n8n')
    - Sends fallback message on final failure
    - Captures synchronous webhook response (both JSON dict & plain string)
    """

    def __init__(self):
        self.webhook_url = settings.N8N_WEBHOOK_URL
        self.max_retries = 3
        self.backoff_delays = [2, 4, 8]  # Exponential backoff: 2s, 4s, 8s

    async def dispatch(
        self,
        payload: N8NDispatchPayload,
        watchdog_instance: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Dispatches inbound message to n8n with 3x exponential backoff.
        """
        if "localhost:5678" in self.webhook_url and settings.USE_MOCK_DB:
            print(f"[n8n Client] Mock mode: Simulated dispatch to {self.webhook_url}")
            return {"status": "dispatched", "attempt": 1, "mock": True}

        callback_url = payload.callback_url or f"{settings.APP_BASE_URL.rstrip('/')}/internal/reply"
        data = {
            "conversation_id": payload.conversation_id,
            "wa_id": payload.wa_id,
            "sessionId": payload.sessionId or payload.wa_id,
            "profile_name": payload.profile_name,
            "message": payload.message or payload.message_body,
            "message_id": payload.message_id or payload.wa_message_id,
            "callback_url": callback_url,
            "leadData": payload.leadData or "",
            "msg_type": payload.msg_type,
            "media_url": payload.media_url,
        }

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "EurekaJo-FastAPI-n8n-Client/1.0",
        }

        last_error_text = ""

        for attempt in range(1, self.max_retries + 1):
            try:
                print(f"[n8n Client] Dispatching message {data['message_id']} to n8n (attempt {attempt}/{self.max_retries})...")
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.post(self.webhook_url, json=data, headers=headers)

                if response.is_success:
                    print(f"[n8n Client] n8n accepted message with HTTP {response.status_code}")
                    bot_text = None
                    if response.content:
                        try:
                            res_json = response.json()
                            if isinstance(res_json, dict):
                                bot_text = (
                                    res_json.get("message")
                                    or res_json.get("reply_text")
                                    or res_json.get("output")
                                    or res_json.get("text")
                                    or res_json.get("response")
                                    or res_json.get("content")
                                )
                            elif isinstance(res_json, str):
                                bot_text = res_json
                        except Exception:
                            # Plain text response from n8n webhook
                            bot_text = response.text

                    if bot_text and bot_text.strip() and bot_text != "{{ $json.final_payload }}":
                        safe_preview = bot_text[:60].encode("ascii", "replace").decode("ascii")
                        print(f"[n8n Client] n8n returned synchronous AI reply: {safe_preview}...")
                        
                        if watchdog_instance:
                            watchdog_instance.resolve_reply(data["message_id"], data["wa_id"])

                        # Deliver to customer via Meta Cloud API
                        meta_res = await meta_service.send_text_message(
                            to_wa_id=data["wa_id"],
                            text=bot_text,
                            reply_to_wa_message_id=data["message_id"],
                        )
                        meta_msg_id = meta_res.get("messages", [{}])[0].get("id")

                        # Log outbound message in database
                        contact = db.upsert_contact(data["wa_id"])
                        await message_log_service.log_outbound_message(
                            conversation_id=data["conversation_id"],
                            contact_id=contact["id"],
                            body=bot_text,
                            wa_message_id=meta_msg_id,
                            msg_type="text",
                            meta_status="sent",
                        )

                    return {
                        "status": "success",
                        "attempt": attempt,
                        "status_code": response.status_code,
                        "sync_reply": bool(bot_text),
                    }

                last_error_text = f"n8n webhook returned HTTP {response.status_code}: {response.text[:200]}"
                print(f"[n8n Client] Attempt {attempt} failed: {last_error_text}")

            except httpx.RequestError as exc:
                last_error_text = f"Connection error on attempt {attempt}: {str(exc)}"
                print(f"[n8n Client] {last_error_text}")

            if attempt < self.max_retries:
                delay = self.backoff_delays[attempt - 1]
                print(f"[n8n Client] Backing off for {delay}s before retry...")
                await asyncio.sleep(delay)

        # Fallback handling on exhausted retries
        print(f"[n8n Client] ALL {self.max_retries} RETRIES FAILED. Triggering fallback reply...")
        db.log_error(
            step="n8n",
            error_text=f"n8n dispatch failed after {self.max_retries} attempts: {last_error_text}",
            conversation_id=data["conversation_id"],
            wa_id=data["wa_id"],
            inbound_body=data["message"],
            payload={"attempts": self.max_retries, "webhook_url": self.webhook_url},
        )

        if watchdog_instance:
            watchdog_instance.resolve_reply(data["message_id"], data["wa_id"])

        fallback_res = await meta_service.send_text_message(
            to_wa_id=data["wa_id"],
            text=settings.FALLBACK_REPLY_TEXT,
            reply_to_wa_message_id=data["message_id"],
        )
        meta_msg_id = fallback_res.get("messages", [{}])[0].get("id")

        contact = db.upsert_contact(data["wa_id"])
        await message_log_service.log_outbound_message(
            conversation_id=data["conversation_id"],
            contact_id=contact["id"],
            body=settings.FALLBACK_REPLY_TEXT,
            wa_message_id=meta_msg_id,
            msg_type="text",
            meta_status="sent",
        )

        return {
            "status": "fallback_triggered",
            "attempts": self.max_retries,
            "error": last_error_text,
        }


n8n_client = N8NClient()
