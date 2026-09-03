import asyncio
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings
from app.models.schemas import N8NDispatchPayload
from app.routers.internal import verify_secret_constant_time
from app.database import db

client = TestClient(app)


def test_callback_secret_constant_time_comparison():
    """Verify constant-time secret comparison against timing attacks"""
    correct_secret = settings.N8N_CALLBACK_SECRET
    assert verify_secret_constant_time(correct_secret) is True
    assert verify_secret_constant_time("wrong_secret_123") is False
    assert verify_secret_constant_time("") is False
    assert verify_secret_constant_time(None) is False


def test_internal_reply_rejection_on_invalid_secret():
    """Verify POST /internal/reply returns HTTP 403 Forbidden on invalid secret"""
    payload = {
        "conversation_id": 1,
        "wa_id": "962791234567",
        "text": "Hello, this should be blocked",
        "status": "ok",
    }
    # No header
    res = client.post("/internal/reply", json=payload)
    assert res.status_code == 403, f"Expected 403 Forbidden, got {res.status_code}"

    # Invalid header
    res = client.post(
        "/internal/reply",
        json=payload,
        headers={"X-Callback-Secret": "invalid_hacker_token"},
    )
    assert res.status_code == 403


def test_internal_reply_success_delivery():
    """Verify POST /internal/reply accepts valid secret and delivers bot reply"""
    contact = db.upsert_contact("962791234567")
    conv = db.resolve_conversation(contact["id"])

    payload = {
        "conversation_id": conv["id"],
        "wa_id": "962791234567",
        "text": "We have 4 luxury apartments available in Abdoun.",
        "status": "ok",
        "reply_to_wa_message_id": "wamid.TEST_MSG_99",
    }

    res = client.post(
        "/internal/reply",
        json=payload,
        headers={"X-Callback-Secret": settings.N8N_CALLBACK_SECRET},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "delivered"
    assert data["message"]["direction"] == "bot"
    assert "luxury apartments" in data["message"]["body"]


def test_internal_reply_error_fallback():
    """Verify POST /internal/reply with status='error' logs error and delivers fallback"""
    initial_errors = len(db.error_logs)

    payload = {
        "conversation_id": 1,
        "wa_id": "962791234567",
        "text": "",
        "status": "error",
        "error_message": "LLM context window exceeded in n8n agent",
    }

    res = client.post(
        "/internal/reply",
        json=payload,
        headers={"X-Callback-Secret": settings.N8N_CALLBACK_SECRET},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "error_handled_with_fallback"
    assert data["message"]["body"] == settings.FALLBACK_REPLY_TEXT
    assert len(db.error_logs) > initial_errors, "Expected error to be written to error_log"


def test_n8n_dispatch_payload_shape():
    """Verify dispatch payload format contains all required keys for n8n"""
    p = N8NDispatchPayload(
        conversation_id=42,
        wa_id="962791112233",
        profile_name="Ahmad Test",
        message="I want to buy a villa",
        message_id="wamid.HBgLOTEyMzQ1NjcVAAYkMWJiMw",
    )
    dump = p.model_dump()
    assert dump["conversation_id"] == 42
    assert dump["wa_id"] == "962791112233"
    assert dump["sessionId"] == "962791112233"
    assert dump["message"] == "I want to buy a villa"
    assert dump["message_id"] == "wamid.HBgLOTEyMzQ1NjcVAAYkMWJiMw"
