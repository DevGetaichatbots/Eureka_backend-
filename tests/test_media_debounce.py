"""
A burst of identical media should earn one canned answer, not one per message.

Conversation 302 (24 Sep 2026): the customer sent three voice notes 2-5 seconds apart and
received three identical "I can't hear voice notes" replies. Nothing was broken - each note
is its own message with its own wa_message_id, so each one was answered - but it reads badly.

Rules being protected here:
  * a run of the SAME media type from one customer collapses to a single reply
  * different media types still get their own reply (voice vs photo say different things)
  * a photo WITH a caption is real intent and is never suppressed
  * text is never suppressed
  * the inbound message is still stored, so the CRM shows every message the customer sent
"""

import asyncio
import re

from app.database import SupabaseDatabase
from app.services.conversation_service import _PLACEHOLDER_BODY, conversation_service


def _fresh_db():
    return SupabaseDatabase()


# ── the guard itself ─────────────────────────────────────────────────────────

def test_repeat_voice_notes_collapse_to_one_reply():
    database = _fresh_db()
    wa_id = "962799847090"

    assert database.claim_media_reply(wa_id, "audio") is True, "first voice note must be answered"
    assert database.claim_media_reply(wa_id, "audio") is False
    assert database.claim_media_reply(wa_id, "audio") is False


def test_a_different_media_type_still_gets_its_own_reply():
    database = _fresh_db()
    wa_id = "962799847090"

    assert database.claim_media_reply(wa_id, "audio") is True
    # "I can't hear voice notes" and "I can't see photos" are different answers.
    assert database.claim_media_reply(wa_id, "image") is True
    assert database.claim_media_reply(wa_id, "sticker") is True


def test_another_customer_is_unaffected():
    database = _fresh_db()
    assert database.claim_media_reply("962700000001", "audio") is True
    assert database.claim_media_reply("962700000002", "audio") is True


def test_a_later_voice_note_is_answered_again(monkeypatch):
    """Someone who reads the reply and sends another note deserves an answer."""
    database = _fresh_db()
    monkeypatch.setattr(type(database), "MEDIA_REPLY_WINDOW_SECONDS", 0)
    assert database.claim_media_reply("962799847090", "audio") is True
    assert database.claim_media_reply("962799847090", "audio") is True


def test_missing_wa_id_is_never_suppressed():
    database = _fresh_db()
    assert database.claim_media_reply("", "audio") is True
    assert database.claim_media_reply(None, "audio") is True


def test_cache_stays_bounded(monkeypatch):
    database = _fresh_db()
    monkeypatch.setattr(type(database), "MEDIA_REPLY_WINDOW_SECONDS", 0)
    for i in range(500):
        database.claim_media_reply(f"96270000{i}", "audio")
    assert len(database._media_replies) <= database.CLAIM_MAX_ENTRIES + 1


# ── which bodies count as "nothing to act on" ────────────────────────────────

def test_placeholder_bodies_are_recognised():
    for body in ("[Voice Note message]", "[Photo message]", "[sticker attachment]",
                 "[reaction attachment]", "[unsupported attachment]", "  [Photo message] "):
        assert _PLACEHOLDER_BODY.match(body), f"{body!r} should count as unreadable media"


def test_real_text_is_never_treated_as_a_placeholder():
    for body in ("مرحبا", "بدي شقة للايجار في خلدا", "[هاي] بدي شقة", "", "٢٠٠"):
        assert not _PLACEHOLDER_BODY.match(body), f"{body!r} must reach the bot"


# ── end to end through the inbound pipeline ──────────────────────────────────

def _stub_pipeline(monkeypatch, dispatched, registered):
    async def fake_mark_read(wa_message_id):
        return {}

    async def fake_upsert(wa_id=None, profile_name=None):
        return {"id": 1, "profile_name": profile_name or "Test"}

    async def fake_resolve(contact_id=None):
        return {"id": 99}

    async def fake_log_inbound(**kwargs):
        return {"id": 1}

    async def fake_dispatch(payload, watchdog_instance=None):
        dispatched.append(payload.message)
        return {"status": "success"}

    import app.services.conversation_service as svc

    monkeypatch.setattr(svc.meta_service, "mark_message_as_read", fake_mark_read)
    monkeypatch.setattr(svc.conv_engine, "upsert_contact", fake_upsert)
    monkeypatch.setattr(svc.conv_engine, "resolve_conversation", fake_resolve)
    monkeypatch.setattr(svc.message_log_service, "log_inbound_message", fake_log_inbound)
    monkeypatch.setattr(svc.n8n_client, "dispatch", fake_dispatch)
    monkeypatch.setattr(
        svc.watchdog, "register_inbound_message",
        lambda **kwargs: registered.append(kwargs["wa_message_id"]),
    )


def _send(body, msg_type, wa_id="962799847090", wa_message_id="wamid.X"):
    return conversation_service.handle_inbound_message(
        wa_id=wa_id,
        profile_name="Test",
        wa_message_id=wa_message_id,
        message_body=body,
        msg_type=msg_type,
    )


def test_three_voice_notes_produce_one_dispatch(monkeypatch):
    dispatched, registered = [], []
    _stub_pipeline(monkeypatch, dispatched, registered)
    monkeypatch.setattr("app.services.conversation_service.db", SupabaseDatabase())

    async def scenario():
        for i in range(3):
            await _send("[Voice Note message]", "audio", wa_message_id=f"wamid.V{i}")

    asyncio.run(scenario())

    assert len(dispatched) == 1, f"expected one reply to the burst, got {len(dispatched)}"
    assert len(registered) == 1, "a suppressed message must not arm a watchdog either"


def test_captioned_photo_is_never_suppressed(monkeypatch):
    dispatched, registered = [], []
    _stub_pipeline(monkeypatch, dispatched, registered)
    monkeypatch.setattr("app.services.conversation_service.db", SupabaseDatabase())

    async def scenario():
        await _send("[Photo message]", "image", wa_message_id="wamid.P1")
        # Same type, inside the window, but this one carries the customer's actual request.
        await _send("بدي شقة للايجار في خلدا", "image", wa_message_id="wamid.P2")

    asyncio.run(scenario())

    assert "بدي شقة للايجار في خلدا" in dispatched, "a captioned photo must reach the bot"
    assert len(dispatched) == 2


def test_text_messages_are_never_suppressed(monkeypatch):
    dispatched, registered = [], []
    _stub_pipeline(monkeypatch, dispatched, registered)
    monkeypatch.setattr("app.services.conversation_service.db", SupabaseDatabase())

    async def scenario():
        for i in range(3):
            await _send("مرحبا", "text", wa_message_id=f"wamid.T{i}")

    asyncio.run(scenario())
    assert len(dispatched) == 3, "text must always be answered"


def test_suppressed_message_is_still_recorded(monkeypatch):
    """The CRM must still show every voice note the customer sent."""
    dispatched, registered = [], []
    logged = []
    _stub_pipeline(monkeypatch, dispatched, registered)
    monkeypatch.setattr("app.services.conversation_service.db", SupabaseDatabase())

    import app.services.conversation_service as svc

    async def fake_log_inbound(**kwargs):
        logged.append(kwargs["wa_message_id"])
        return {"id": len(logged)}

    monkeypatch.setattr(svc.message_log_service, "log_inbound_message", fake_log_inbound)

    async def scenario():
        for i in range(3):
            await _send("[Voice Note message]", "audio", wa_message_id=f"wamid.V{i}")

    asyncio.run(scenario())

    assert logged == ["wamid.V0", "wamid.V1", "wamid.V2"], "all three must appear in the CRM"
    assert len(dispatched) == 1
