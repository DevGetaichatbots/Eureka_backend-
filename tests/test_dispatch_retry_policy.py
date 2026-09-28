"""
A timeout and an unreachable host are not the same failure.

26 Sep 2026, conversation 325. One customer asked for five results in each of six areas,
filtered by building age - which the search API cannot filter on. The agent went hunting:
110 LLM calls, 109 tool calls, 410 seconds. Meanwhile the backend timed out at 45s and
retried. Twice. Each retry started a FRESH agent run of the same message:

    exec 18972  23:36:53 -> 23:43:43   410s   110 LLM calls
    exec 18984  23:37:40 -> 23:41:14   214s    53 LLM calls
    exec 19011  23:38:30 -> 23:41:23   174s    45 LLM calls

All three finished successfully and all three answers were thrown away, because by then
nobody was waiting. 208 LLM calls burned, and the customer got two apologies.

A read timeout means n8n ACCEPTED the work and is still doing it - retrying can only
duplicate it. A connection error means n8n never took it - retrying is the right move.
"""

import asyncio

import httpx
import pytest

from app.database import SupabaseDatabase, db
from app.services.n8n_client import N8NClient
from app.models.schemas import N8NDispatchPayload


def _payload():
    return N8NDispatchPayload(
        wa_id="962797673243",
        profile_name="Sabrina",
        message="بلش فيهم بالترتيب وطلع لي من كل منطقه افضل ٥ نتائج",
        message_body="بلش فيهم بالترتيب وطلع لي من كل منطقه افضل ٥ نتائج",
        msg_type="text",
        conversation_id=325,
        message_id="wamid.HEAVY_REQUEST",
        wa_message_id="wamid.HEAVY_REQUEST",
    )


def _silence_fallback(monkeypatch, sent):
    """Stop the give-up path from touching Meta or Supabase."""
    import app.services.n8n_client as mod

    async def fake_send(to_wa_id=None, text=None, reply_to_wa_message_id=None, **kwargs):
        sent.append(text)
        return {"messages": [{"id": "wamid.FALLBACK"}]}

    async def fake_log_outbound(**kwargs):
        return {"id": 1}

    monkeypatch.setattr(mod.meta_service, "send_text_message", fake_send)
    monkeypatch.setattr(mod.message_log_service, "log_outbound_message", fake_log_outbound)
    monkeypatch.setattr(mod.db, "log_error", lambda **kwargs: {})
    monkeypatch.setattr(mod.db, "upsert_contact", lambda wa_id: {"id": 1})
    monkeypatch.setattr(mod.db, "claim_fallback", lambda wamid: True)


def _make_client():
    """
    A client pointed at a real-looking URL. dispatch() short-circuits into mock mode for
    localhost:5678 when USE_MOCK_DB is set, which the local test .env does.
    """
    client = N8NClient()
    client.webhook_url = "https://eurekajo.app.n8n.cloud/webhook/chatbase-eureka"
    return client


def _client_raising(monkeypatch, exc, attempts):
    """Make every httpx POST raise `exc`, counting the attempts."""
    import app.services.n8n_client as mod

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            attempts.append(1)
            raise exc

    monkeypatch.setattr(mod.httpx, "AsyncClient", FakeAsyncClient)

    # Skip the backoff waits. Bind the real sleep first - patching asyncio.sleep with a
    # lambda that calls asyncio.sleep would just call the patched version forever.
    real_sleep = asyncio.sleep

    async def no_wait(*_args, **_kwargs):
        await real_sleep(0)

    monkeypatch.setattr(mod.asyncio, "sleep", no_wait)


def test_a_read_timeout_is_not_retried(monkeypatch):
    """The workflow is still running - a retry would duplicate it."""
    attempts, sent = [], []
    _silence_fallback(monkeypatch, sent)
    _client_raising(monkeypatch, httpx.ReadTimeout("timed out"), attempts)

    result = asyncio.run(_make_client().dispatch(_payload()))

    assert len(attempts) == 1, (
        f"a read timeout must stop after one attempt, got {len(attempts)} - each extra "
        f"attempt starts another full agent run of the same message"
    )
    assert "not retried" in result["error"]


def test_a_connection_error_is_retried(monkeypatch):
    """n8n never took the work, so retrying is safe and correct."""
    attempts, sent = [], []
    _silence_fallback(monkeypatch, sent)
    _client_raising(monkeypatch, httpx.ConnectError("refused"), attempts)

    client = _make_client()
    asyncio.run(client.dispatch(_payload()))

    assert len(attempts) == client.max_retries, (
        f"an unreachable n8n should still be retried {client.max_retries}x, got {len(attempts)}"
    )


def test_the_customer_is_still_told_when_we_give_up(monkeypatch):
    """Not retrying must not mean staying silent."""
    attempts, sent = [], []
    _silence_fallback(monkeypatch, sent)
    _client_raising(monkeypatch, httpx.ReadTimeout("timed out"), attempts)

    asyncio.run(_make_client().dispatch(_payload()))
    assert len(sent) == 1, "the customer must still receive exactly one apology"


# ── one apology per message, not two ─────────────────────────────────────────

def test_only_one_fallback_is_allowed_per_message():
    database = SupabaseDatabase()
    assert database.claim_fallback("wamid.X") is True, "the first path may apologise"
    assert database.claim_fallback("wamid.X") is False, "the second must stay quiet"


def test_fallbacks_for_different_messages_are_independent():
    database = SupabaseDatabase()
    assert database.claim_fallback("wamid.A") is True
    assert database.claim_fallback("wamid.B") is True


def test_a_missing_message_id_is_never_silenced():
    database = SupabaseDatabase()
    assert database.claim_fallback("") is True
    assert database.claim_fallback(None) is True


def test_fallback_claim_does_not_collide_with_inbound_claim():
    """
    Both guards share one dict. A fallback claim must not make the backend think the
    inbound message itself was already processed, or the next delivery would be dropped.
    """
    database = SupabaseDatabase()
    wamid = "wamid.SHARED"
    assert database.claim_fallback(wamid) is True
    assert database.claim_message(wamid) is True, (
        "claiming a fallback must not consume the inbound claim for the same id"
    )
