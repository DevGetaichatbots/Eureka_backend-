import asyncio
from datetime import datetime, timezone, timedelta
from app.services.conversation import conversation_service, normalize_wa_id
from app.services.message_log import message_log_service
from app.database import db


def test_contact_normalization_and_upsert():
    """Verify phone normalization to E.164 without '+' and contact upserting"""
    assert normalize_wa_id("+962 79 123-4567") == "962791234567"
    assert normalize_wa_id("+1 (555) 671-2685") == "15556712685"

    contact1 = asyncio.run(conversation_service.upsert_contact(
        wa_id="+962799887766",
        profile_name="Zaid Real Estate",
    ))
    assert contact1["wa_id"] == "962799887766"
    assert contact1["profile_name"] == "Zaid Real Estate"

    # Second upsert updates profile name if changed
    contact2 = asyncio.run(conversation_service.upsert_contact(
        wa_id="962799887766",
        profile_name="Zaid Mansour",
    ))
    assert contact2["id"] == contact1["id"]
    assert contact2["profile_name"] == "Zaid Mansour"


def test_24h_conversation_windowing():
    """
    Verify 24-hour windowing:
    - Inbound at T0 -> Conv A
    - Inbound at T0 + 2h -> Conv A (same conversation, message_count bumped)
    - Inbound at T0 + 25h -> Conv B (new conversation opened)
    """
    t0 = datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc)

    # 1. First contact and first conversation at T0
    contact = asyncio.run(conversation_service.upsert_contact(wa_id="962790011223"))
    conv_initial = asyncio.run(conversation_service.resolve_conversation(
        contact_id=contact["id"],
        current_time=t0,
    ))
    initial_conv_id = conv_initial["id"]
    assert conv_initial["message_count"] == 1
    assert conv_initial["started_at"] == t0

    # 2. Customer messages 2 hours later (within 24h window) -> Same conversation
    t_within = t0 + timedelta(hours=2)
    conv_same = asyncio.run(conversation_service.resolve_conversation(
        contact_id=contact["id"],
        current_time=t_within,
    ))
    assert conv_same["id"] == initial_conv_id, "Expected message within 24h to append to the same conversation"
    assert conv_same["message_count"] == 2
    assert conv_same["last_message_at"] == t_within

    # 3. Customer messages 25 hours later (exceeds 24h window) -> New conversation opened
    t_expired = t_within + timedelta(hours=25)
    conv_new = asyncio.run(conversation_service.resolve_conversation(
        contact_id=contact["id"],
        current_time=t_expired,
    ))
    assert conv_new["id"] != initial_conv_id, "Expected message after 24h to open a new conversation"
    assert conv_new["message_count"] == 1
    assert conv_new["started_at"] == t_expired


def test_message_logging_types():
    """Verify inbound customer logging and outbound bot logging with non-text types"""
    contact = asyncio.run(conversation_service.upsert_contact(wa_id="962795554433"))
    conv = asyncio.run(conversation_service.resolve_conversation(contact_id=contact["id"]))

    # Inbound text message
    inbound_text = asyncio.run(message_log_service.log_inbound_message(
        conversation_id=conv["id"],
        contact_id=contact["id"],
        wa_message_id="wamid.TEST_INBOUND_01",
        body="Do you have 2-bedroom apartments in Abdoun?",
        msg_type="text",
    ))
    assert inbound_text["direction"] == "customer"
    assert inbound_text["wa_message_id"] == "wamid.TEST_INBOUND_01"

    # Inbound image attachment (must not crash)
    inbound_image = asyncio.run(message_log_service.log_inbound_message(
        conversation_id=conv["id"],
        contact_id=contact["id"],
        wa_message_id="wamid.TEST_INBOUND_IMG",
        body="[Photo of floor plan]",
        msg_type="image",
        media_url="https://media.meta.com/img_123",
    ))
    assert inbound_image["direction"] == "customer"
    assert inbound_image["msg_type"] == "image"

    # Outbound bot reply
    outbound_reply = asyncio.run(message_log_service.log_outbound_message(
        conversation_id=conv["id"],
        contact_id=contact["id"],
        body="Yes, we have 3 apartments available in Abdoun starting at 75,000 JOD.",
        wa_message_id="wamid.TEST_OUTBOUND_01",
    ))
    assert outbound_reply["direction"] == "bot"
    assert outbound_reply["meta_status"] == "sent"
