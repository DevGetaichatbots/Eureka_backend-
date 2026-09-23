"""
Regression tests for duplicate WhatsApp webhook delivery.

Observed in production (16-17 Sep 2026): Meta delivered the same wa_message_id twice,
30-40ms apart. Two things went wrong as a result.

1. Both copies were dispatched to n8n, so the customer received the bot's answer twice.
   The idempotency guard could not catch it because `mark_message_processed` was a no-op
   and `is_message_duplicate` only looks at the `messages` table, which is not written
   until later, inside the background task.

2. Exactly 60s after the duplicate, the customer also received the English fallback
   ("Sorry, I'm having trouble answering right now."), even though n8n had answered
   correctly in ~8s. The second `register_inbound_message` cancelled the first task and
   replaced it in `pending_tasks`; when the cancelled task later ran its `finally`, it
   popped the *replacement* out of the dict. That left a live timer nobody could cancel.

These tests use no network and no database.
"""

import asyncio
from types import SimpleNamespace

from app.services import watchdog as watchdog_module
from app.services.watchdog import ReplyWatchdog

WAMID = "wamid.DUPLICATE_DELIVERY_TEST"
TIMEOUT = 0.15


class Recorder:
    def __init__(self):
        self.fallbacks = []
        self.errors = []


def _isolate_watchdog(monkeypatch, recorder, timeout=TIMEOUT):
    """Replace every outbound dependency of the watchdog with a recorder."""

    async def fake_send_text_message(to_wa_id=None, text=None, reply_to_wa_message_id=None, **kwargs):
        recorder.fallbacks.append(text)
        return {"messages": [{"id": "wamid.FAKE_FALLBACK"}]}

    def fake_log_error(**kwargs):
        recorder.errors.append(kwargs)
        return {}

    monkeypatch.setattr(watchdog_module.meta_service, "send_text_message", fake_send_text_message)
    monkeypatch.setattr(watchdog_module.db, "log_error", fake_log_error)
    monkeypatch.setattr(watchdog_module.db, "upsert_contact", lambda wa_id: {"id": 1})
    monkeypatch.setattr(watchdog_module.db, "insert_message", lambda **kwargs: {"id": 1})
    monkeypatch.setattr(
        watchdog_module,
        "settings",
        SimpleNamespace(WATCHDOG_TIMEOUT_SECONDS=timeout, FALLBACK_REPLY_TEXT="FALLBACK_SENT"),
    )


def _register(w, text="مرحبا"):
    w.register_inbound_message(
        wa_id="962791234567",
        conversation_id=1,
        wa_message_id=WAMID,
        inbound_text=text,
    )


def test_duplicate_delivery_does_not_leave_an_orphan_timer(monkeypatch):
    """
    The production bug: same message registered twice, answered once, fallback still fired.
    """
    recorder = Recorder()
    _isolate_watchdog(monkeypatch, recorder)

    async def scenario():
        w = ReplyWatchdog()

        # First delivery. In production `handle_inbound_message` awaits several I/O calls
        # after registering, so this timer is genuinely running before the duplicate lands.
        _register(w)
        await asyncio.sleep(0.02)

        # Meta delivers the same message again, milliseconds later.
        _register(w)

        # Let the cancelled first task run its `finally` block.
        await asyncio.sleep(0.02)

        # n8n answers once, as it did in production (~8s, well inside the window).
        w.resolve_reply(WAMID, "962791234567")

        # Wait past the timeout: nothing should fire.
        await asyncio.sleep(timeout_margin())
        return w

    w = asyncio.run(scenario())

    assert recorder.fallbacks == [], (
        f"a fallback was sent even though n8n replied in time: {recorder.fallbacks}"
    )
    assert recorder.errors == [], f"a watchdog timeout was logged unexpectedly: {recorder.errors}"
    assert w.pending_tasks == {}, f"watchdog leaked state: {w.pending_tasks}"


def test_single_message_answered_in_time_sends_no_fallback(monkeypatch):
    recorder = Recorder()
    _isolate_watchdog(monkeypatch, recorder)

    async def scenario():
        w = ReplyWatchdog()
        _register(w)
        w.resolve_reply(WAMID, "962791234567")
        await asyncio.sleep(timeout_margin())
        return w

    w = asyncio.run(scenario())
    assert recorder.fallbacks == []
    assert w.pending_tasks == {}


def test_unanswered_message_still_sends_the_fallback(monkeypatch):
    """The watchdog must keep working - this is the behaviour we are protecting."""
    recorder = Recorder()
    _isolate_watchdog(monkeypatch, recorder)

    async def scenario():
        w = ReplyWatchdog()
        _register(w)
        await asyncio.sleep(timeout_margin())
        return w

    w = asyncio.run(scenario())
    assert recorder.fallbacks == ["FALLBACK_SENT"], "watchdog stopped protecting silent failures"
    assert len(recorder.errors) == 1
    assert w.pending_tasks == {}


def test_duplicate_then_silence_still_sends_exactly_one_fallback(monkeypatch):
    """Two deliveries, no answer at all: the customer must not get two apologies."""
    recorder = Recorder()
    _isolate_watchdog(monkeypatch, recorder)

    async def scenario():
        w = ReplyWatchdog()
        _register(w)
        await asyncio.sleep(0.02)
        _register(w)
        await asyncio.sleep(0.02)
        await asyncio.sleep(timeout_margin())
        return w

    w = asyncio.run(scenario())
    assert recorder.fallbacks == ["FALLBACK_SENT"], (
        f"expected exactly one fallback, got {len(recorder.fallbacks)}: {recorder.fallbacks}"
    )
    assert w.pending_tasks == {}


def timeout_margin():
    return TIMEOUT * 3
