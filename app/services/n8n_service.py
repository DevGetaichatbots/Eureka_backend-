import httpx
from typing import Dict, Any
from app.config import settings
from app.database import db
from app.models.schemas import N8NDispatchPayload


class N8NService:
    def __init__(self):
        self.webhook_url = settings.N8N_WEBHOOK_URL

    async def dispatch_inbound_message(self, payload: N8NDispatchPayload) -> bool:
        """
        Dispatches the normalized inbound WhatsApp message to the n8n AI Bot workflow webhook.
        """
        # In mock mode, log and simulate successful receipt
        if settings.USE_MOCK_DB or "localhost:5678" in self.webhook_url:
            print(f"[n8n Service] Simulated dispatch to {self.webhook_url}: {payload.message_body[:60]}...")
            return True

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "EurekaJo-FastAPI-Bridge/1.0",
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(
                    self.webhook_url,
                    json=payload.model_dump(),
                    headers=headers,
                )
                if not res.is_success:
                    db.log_error(
                        step="n8n",
                        error_text=f"n8n webhook returned HTTP {res.status_code}",
                        conversation_id=payload.conversation_id,
                        wa_id=payload.wa_id,
                        inbound_body=payload.message_body,
                        payload={"response_text": res.text},
                    )
                    return False
                return True
        except httpx.RequestError as exc:
            db.log_error(
                step="n8n",
                error_text=f"n8n connection failed: {str(exc)}",
                conversation_id=payload.conversation_id,
                wa_id=payload.wa_id,
                inbound_body=payload.message_body,
            )
            return False


n8n_service = N8NService()
