import hmac
import hashlib
import time
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings
from app.database import db

client = TestClient(app)


def test_webhook_verification_handshake():
    """GET /webhook/whatsapp: Valid verify_token returns challenge as plain text"""
    challenge = "test_challenge_12345"
    res = client.get(
        f"/webhook/whatsapp?hub.mode=subscribe&hub.verify_token={settings.META_VERIFY_TOKEN}&hub.challenge={challenge}"
    )
    assert res.status_code == 200
    assert res.text == challenge


def test_webhook_verification_mismatch():
    """GET /webhook/whatsapp: Invalid verify_token rejected with 403"""
    res = client.get(
        "/webhook/whatsapp?hub.mode=subscribe&hub.verify_token=wrong_token&hub.challenge=12345"
    )
    assert res.status_code == 403


def test_webhook_signature_and_fast_ack():
    """POST /webhook/whatsapp: Valid signature accepted and acknowledged in under 300ms"""
    payload = b'{"entry": []}'
    sig = hmac.new(
        key=settings.META_APP_SECRET.encode("utf-8"),
        msg=payload,
        digestmod=hashlib.sha256,
    ).hexdigest()

    start_time = time.perf_counter()
    res = client.post(
        "/webhook/whatsapp",
        content=payload,
        headers={
            "X-Hub-Signature-256": f"sha256={sig}",
            "Content-Type": "application/json",
        },
    )
    duration_ms = (time.perf_counter() - start_time) * 1000

    assert res.status_code == 200
    assert duration_ms < 300, f"Ack took {duration_ms:.2f}ms, target is under 300ms"


def test_webhook_deduplication():
    """Duplicate wa_message_id is acknowledged with 200 immediately without reprocessing"""
    test_wamid = "wamid.DEDUP_TEST_9999"
    # Mark as already processed
    db.mark_message_processed(test_wamid)

    # Send payload with this wamid
    raw_payload = f'{{"entry": [{{"changes": [{{"value": {{"messages": [{{"id": "{test_wamid}", "from": "962791234567", "type": "text", "text": {{"body": "Hello"}}}}]}}}}]}}]}}'.encode("utf-8")
    sig = hmac.new(
        key=settings.META_APP_SECRET.encode("utf-8"),
        msg=raw_payload,
        digestmod=hashlib.sha256,
    ).hexdigest()

    res = client.post(
        "/webhook/whatsapp",
        content=raw_payload,
        headers={
            "X-Hub-Signature-256": f"sha256={sig}",
            "Content-Type": "application/json",
        },
    )
    assert res.status_code == 200
