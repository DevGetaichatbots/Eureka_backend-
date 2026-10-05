import hmac
import hashlib
import json
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings
from app.database import db

client = TestClient(app)


def _post_signed(body: dict):
    raw = json.dumps(body).encode("utf-8")
    sig = hmac.new(settings.META_APP_SECRET.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    return client.post(
        "/webhook/whatsapp",
        content=raw,
        headers={"X-Hub-Signature-256": f"sha256={sig}", "Content-Type": "application/json"},
    )


def _status_payload(status: str, wamid: str = "wamid.OUT1", errors=None) -> dict:
    st = {"id": wamid, "status": status, "recipient_id": "962790286730", "timestamp": "1790000000"}
    if errors:
        st["errors"] = errors
    return {"entry": [{"changes": [{"value": {"statuses": [st]}}]}]}


def test_delivered_callback_updates_portal_status(monkeypatch):
    """A 'delivered' callback for a bot reply must update that message's meta_status."""
    seen = []
    monkeypatch.setattr(db, "update_message_status", lambda wid, s: seen.append((wid, s)))
    res = _post_signed(_status_payload("delivered"))
    assert res.status_code == 200
    assert seen == [("wamid.OUT1", "delivered")]


def test_read_callback_updates_portal_status(monkeypatch):
    seen = []
    monkeypatch.setattr(db, "update_message_status", lambda wid, s: seen.append((wid, s)))
    _post_signed(_status_payload("read"))
    assert seen == [("wamid.OUT1", "read")]


def test_failed_callback_marks_message_and_logs_reason(monkeypatch):
    """A 'failed' callback must mark the message failed AND record Meta's error, not stay 'sent'."""
    seen, logged = [], []
    monkeypatch.setattr(db, "update_message_status", lambda wid, s: seen.append((wid, s)))
    monkeypatch.setattr(db, "log_error", lambda **kw: logged.append(kw))
    errors = [{"code": 131049, "title": "Message undeliverable"}]
    _post_signed(_status_payload("failed", errors=errors))

    assert seen == [("wamid.OUT1", "failed")]
    assert len(logged) == 1
    assert logged[0]["step"] == "meta_delivery"
    assert "131049" in logged[0]["error_text"]
    assert logged[0]["wa_id"] == "962790286730"


def test_unknown_status_is_ignored(monkeypatch):
    seen = []
    monkeypatch.setattr(db, "update_message_status", lambda wid, s: seen.append((wid, s)))
    _post_signed(_status_payload("weird_state"))
    assert seen == []


import asyncio
from app.services.conversation_service import InboundPipelineCoordinator
from app.services import conversation_service as cs_module


def _run_inbound_with_store(monkeypatch, store_behaviour):
    """Drive handle_inbound_message with the DB-write step scripted per attempt."""
    calls = {"store": 0, "release": [], "errors": [], "dispatch": 0}

    async def fake_store(self, *args, **kwargs):
        calls["store"] += 1
        outcome = store_behaviour(calls["store"])
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def no_read_receipt(*args, **kwargs):
        return True

    async def fake_dispatch(*args, **kwargs):
        calls["dispatch"] += 1

    async def no_sleep(*args, **kwargs):
        return None

    monkeypatch.setattr(InboundPipelineCoordinator, "_store_inbound", fake_store)
    monkeypatch.setattr(cs_module.meta_service, "mark_message_as_read", no_read_receipt)
    monkeypatch.setattr(cs_module.n8n_client, "dispatch", fake_dispatch)
    monkeypatch.setattr(cs_module.watchdog, "register_inbound_message", lambda **kw: None)
    monkeypatch.setattr(cs_module.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(db, "release_claim", lambda wid: calls["release"].append(wid))
    monkeypatch.setattr(db, "log_error", lambda **kw: calls["errors"].append(kw))

    result = asyncio.run(
        InboundPipelineCoordinator().handle_inbound_message(
            wa_id="962790286730",
            profile_name="Test",
            wa_message_id="wamid.IN1",
            message_body="بدي شقة",
            msg_type="text",
        )
    )
    return result, calls


def test_inbound_store_retries_then_succeeds(monkeypatch):
    """A transient DB error must be retried, and the reply still dispatched exactly once."""
    stored = {
        "contact": {"id": 1, "wa_id": "962790286730"},
        "conversation": {"id": 2},
        "message": {"id": 3},
    }

    def behaviour(n):
        return ConnectionError("name or service not known") if n < 3 else stored

    result, calls = _run_inbound_with_store(monkeypatch, behaviour)
    assert calls["store"] == 3
    assert calls["dispatch"] == 1
    assert calls["release"] == []
    assert calls["errors"] == []


def test_inbound_store_gives_up_releases_claim_and_logs(monkeypatch):
    """After all attempts fail: nothing dispatched, claim released, and a record left for the team."""
    result, calls = _run_inbound_with_store(
        monkeypatch, lambda n: ConnectionError("name or service not known")
    )
    assert calls["store"] == InboundPipelineCoordinator.INBOUND_STORE_ATTEMPTS
    assert calls["dispatch"] == 0
    assert calls["release"] == ["wamid.IN1"]
    assert len(calls["errors"]) == 1
    assert calls["errors"][0]["step"] == "inbound_store"
    assert calls["errors"][0]["wa_id"] == "962790286730"
    assert result == {"stored": False}
