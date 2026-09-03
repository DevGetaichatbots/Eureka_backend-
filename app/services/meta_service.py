import asyncio
import httpx
from typing import Dict, Any, Optional
from app.config import settings
from app.database import db


class MetaWhatsAppService:
    def __init__(self):
        self.api_version = settings.META_API_VERSION
        self.phone_number_id = settings.META_PHONE_NUMBER_ID
        self.access_token = settings.META_GRAPH_API_TOKEN
        self.base_url = f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/messages"

    @property
    def headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    async def send_text_message(
        self,
        to_wa_id: str,
        text: str,
        reply_to_wa_message_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Sends an outbound text message to a customer's WhatsApp number via Meta Cloud API
        with 3-attempt exponential backoff retry on transient errors or timeouts.
        """
        payload: Dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_wa_id,
            "type": "text",
            "text": {
                "preview_url": True,
                "body": text,
            },
        }

        if reply_to_wa_message_id:
            payload["context"] = {"message_id": reply_to_wa_message_id}

        if settings.USE_MOCK_DB or settings.META_GRAPH_API_TOKEN == "mock_graph_token":
            return {
                "messaging_product": "whatsapp",
                "contacts": [{"input": to_wa_id, "wa_id": to_wa_id}],
                "messages": [{"id": f"wamid.mock.{to_wa_id[-4:]}.{hash(text) % 10000}"}],
            }

        max_attempts = 3
        last_error_desc = ""

        for attempt in range(1, max_attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    res = await client.post(self.base_url, json=payload, headers=self.headers)
                    if res.is_success:
                        return res.json()

                    error_data = res.json() if res.content else {"error": res.text}
                    last_error_desc = f"HTTP {res.status_code}: {res.text[:200]}"
                    db.log_error(
                        step="meta_send",
                        error_text=f"Meta API send attempt {attempt}/{max_attempts} failed with {last_error_desc}",
                        wa_id=to_wa_id,
                        inbound_body=text,
                        payload=error_data,
                    )
                    if attempt < max_attempts:
                        await asyncio.sleep(1.5 * attempt)
                        continue

            except Exception as exc:
                last_error_desc = f"Network Exception: {str(exc)}"
                db.log_error(
                    step="meta_send",
                    error_text=f"Meta API error attempt {attempt}/{max_attempts}: {last_error_desc}",
                    wa_id=to_wa_id,
                    inbound_body=text,
                )
                if attempt < max_attempts:
                    await asyncio.sleep(1.5 * attempt)
                    continue

        # Return graceful fallback dictionary if Meta API fails after 3 retries
        return {
            "messaging_product": "whatsapp",
            "contacts": [{"input": to_wa_id, "wa_id": to_wa_id}],
            "messages": [{"id": f"wamid.fallback.{hash(text) % 10000}"}],
            "error_detail": last_error_desc,
        }

    async def mark_message_as_read(self, wa_message_id: str) -> bool:
        """Sends read receipt status checkmark to Meta"""
        if settings.USE_MOCK_DB or settings.META_GRAPH_API_TOKEN == "mock_graph_token":
            return True

        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": wa_message_id,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(self.base_url, json=payload, headers=self.headers)
                return res.is_success
        except Exception:
            return False


meta_service = MetaWhatsAppService()
