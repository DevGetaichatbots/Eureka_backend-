"""
Regression tests for the inbound idempotency guard.

Production symptom (16-17 Sep 2026): the same wa_message_id reached the n8n workflow
twice, 30-40ms apart, so customers received every bot answer twice.

Root cause: `webhook.py` checked `db.is_message_duplicate(...)` and only marked the
message afterwards, and `db.mark_message_processed(...)` was an empty `pass`. The check
reads the `messages` table, which is not written until later inside the background task,
so two near-simultaneous deliveries both saw "not a duplicate".

`db.claim_message()` now performs a single atomic claim instead.
These tests use no network: the durable Supabase lookup is stubbed out.
"""

import hashlib
import hmac
import json
import threading

from fastapi.testclient import TestClient

from app.config import settings
from app.database import SupabaseDatabase, db
from app.main import app


def _fresh_db(monkeypatch, durable_duplicate=False):
    """A database instance whose slow Supabase lookup is replaced by a stub."""
    database = SupabaseDatabase()
    monkeypatch.setattr(
        type(database), "is_message_duplicate", lambda self, wamid: durable_duplicate
    )
    return database


def test_first_claim_wins_and_second_is_rejected(monkeypatch):
    database = _fresh_db(monkeypatch)
    wamid = "wamid.CLAIM_ONCE"

    assert database.claim_message(wamid) is True, "the first delivery must be processed"
    assert database.claim_message(wamid) is False, "the duplicate delivery must be dropped"


def test_distinct_messages_are_all_processed(monkeypatch):
    database = _fresh_db(monkeypatch)
    assert database.claim_message("wamid.A") is True
    assert database.claim_message("wamid.B") is True
    assert database.claim_message("wamid.C") is True


def test_concurrent_deliveries_of_one_message_yield_exactly_one_winner(monkeypatch):
    """
    The actual production race: two webhook deliveries handled at the same moment.
    Before the fix both callers were told to process the message.
    """
    database = _fresh_db(monkeypatch)
    wamid = "wamid.CONCURRENT_DELIVERY"

    results = []
    results_lock = threading.Lock()
    start = threading.Barrier(8)

    def deliver():
        start.wait()  # make all threads collide on the claim
        won = database.claim_message(wamid)
        with results_lock:
            results.append(won)

    threads = [threading.Thread(target=deliver) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count(True) == 1, (
        f"expected exactly one winner out of 8 concurrent deliveries, got {results.count(True)}"
    )
    assert results.count(False) == 7


def test_message_already_in_the_database_is_rejected(monkeypatch):
    """A redelivery arriving after a restart is caught by the durable check."""
    database = _fresh_db(monkeypatch, durable_duplicate=True)
    assert database.claim_message("wamid.SEEN_BEFORE_RESTART") is False


def test_supabase_failure_does_not_drop_a_real_message(monkeypatch):
    """If the durable lookup errors we must still serve the customer."""
    database = SupabaseDatabase()

    def explode(self, wamid):
        raise RuntimeError("supabase unreachable")

    monkeypatch.setattr(type(database), "is_message_duplicate", explode)
    assert database.claim_message("wamid.DB_DOWN") is True
    # ...but the in-process claim still blocks the duplicate.
    assert database.claim_message("wamid.DB_DOWN") is False


def test_mark_message_processed_blocks_a_later_claim(monkeypatch):
    database = _fresh_db(monkeypatch)
    wamid = "wamid.PRE_MARKED"

    database.mark_message_processed(wamid)
    assert database.claim_message(wamid) is False


def test_missing_message_id_is_never_dropped(monkeypatch):
    database = _fresh_db(monkeypatch)
    assert database.claim_message("") is True
    assert database.claim_message(None) is True


def _signed_post(client, wamid, body="مرحبا", msg_type="text"):
    """Post a Meta-shaped webhook carrying a single message."""
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [{"profile": {"name": "Test User"}}],
                            "messages": [
                                {
                                    "id": wamid,
                                    "from": "962791234567",
                                    "type": msg_type,
                                    "text": {"body": body},
                                    "timestamp": "1789000000",
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }
    raw = json.dumps(payload).encode("utf-8")
    signature = hmac.new(
        key=settings.META_APP_SECRET.encode("utf-8"), msg=raw, digestmod=hashlib.sha256
    ).hexdigest()
    return client.post(
        "/webhook/whatsapp",
        content=raw,
        headers={
            "X-Hub-Signature-256": f"sha256={signature}",
            "Content-Type": "application/json",
        },
    )


def test_duplicate_webhook_delivery_dispatches_to_n8n_only_once(monkeypatch):
    """
    End-to-end through the real route: Meta delivers the same message twice and only one
    dispatch may reach the inbound pipeline. Previously both were dispatched and the
    customer saw the bot's answer twice.
    """
    dispatched = []

    async def fake_handle_inbound_message(**kwargs):
        dispatched.append(kwargs["wa_message_id"])
        return {}

    # Keep the route entirely off the network.
    monkeypatch.setattr(db, "is_message_duplicate", lambda wamid: False)
    monkeypatch.setattr(
        "app.routers.webhook.conversation_service.handle_inbound_message",
        fake_handle_inbound_message,
    )

    wamid = "wamid.E2E_DUPLICATE_DELIVERY"
    with TestClient(app) as client:
        first = _signed_post(client, wamid)
        second = _signed_post(client, wamid)

    # Meta must always be acknowledged, duplicate or not.
    assert first.status_code == 200
    assert second.status_code == 200

    assert dispatched == [wamid], (
        f"expected a single dispatch for a duplicated delivery, got {len(dispatched)}: {dispatched}"
    )


def test_two_different_messages_are_both_dispatched(monkeypatch):
    dispatched = []

    async def fake_handle_inbound_message(**kwargs):
        dispatched.append(kwargs["wa_message_id"])
        return {}

    monkeypatch.setattr(db, "is_message_duplicate", lambda wamid: False)
    monkeypatch.setattr(
        "app.routers.webhook.conversation_service.handle_inbound_message",
        fake_handle_inbound_message,
    )

    with TestClient(app) as client:
        _signed_post(client, "wamid.E2E_FIRST", body="مرحبا")
        _signed_post(client, "wamid.E2E_SECOND", body="بدي شقة")

    assert dispatched == ["wamid.E2E_FIRST", "wamid.E2E_SECOND"]


def test_voice_note_is_labelled_and_dispatched_once(monkeypatch):
    """Voice notes are the case the customer reported; they must dispatch exactly once."""
    dispatched = []

    async def fake_handle_inbound_message(**kwargs):
        dispatched.append((kwargs["wa_message_id"], kwargs["message_body"], kwargs["msg_type"]))
        return {}

    monkeypatch.setattr(db, "is_message_duplicate", lambda wamid: False)
    monkeypatch.setattr(
        "app.routers.webhook.conversation_service.handle_inbound_message",
        fake_handle_inbound_message,
    )

    wamid = "wamid.E2E_VOICE_NOTE"
    with TestClient(app) as client:
        _signed_post(client, wamid, msg_type="audio")
        _signed_post(client, wamid, msg_type="audio")

    assert len(dispatched) == 1, f"voice note dispatched {len(dispatched)} times"
    assert dispatched[0][1] == "[Voice Note message]"
    assert dispatched[0][2] == "audio"


def test_claim_cache_stays_bounded(monkeypatch):
    database = _fresh_db(monkeypatch)
    monkeypatch.setattr(type(database), "CLAIM_MAX_ENTRIES", 50)

    for i in range(500):
        database.claim_message(f"wamid.BULK_{i}")

    assert len(database._claimed_messages) <= 51, (
        f"claim cache grew unbounded: {len(database._claimed_messages)} entries"
    )
