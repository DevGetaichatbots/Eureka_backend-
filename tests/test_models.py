from datetime import datetime, timezone
from app.db.models import Base, Contact, Conversation, Message, ErrorLog, AppUser


def test_models_metadata():
    """Verify all 5 required tables exist in metadata with no bot_config or knowledge_sources"""
    table_names = set(Base.metadata.tables.keys())
    expected_tables = {"contacts", "conversations", "messages", "error_log", "app_users"}
    assert expected_tables.issubset(table_names), f"Missing tables: {expected_tables - table_names}"

    # Scope check: no bot_config or knowledge_sources table
    assert "bot_config" not in table_names, "bot_config table must not exist (owned by n8n)"
    assert "knowledge_sources" not in table_names, "knowledge_sources table must not exist (owned by n8n)"


def test_model_instantiation():
    """Verify models instantiate with proper columns and relationships"""
    contact = Contact(
        wa_id="962791234567",
        profile_name="Tariq Mansour",
        first_seen_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
        message_count=1,
    )
    assert contact.wa_id == "962791234567"
    assert contact.profile_name == "Tariq Mansour"

    conversation = Conversation(
        contact_id=1,
        started_at=datetime.now(timezone.utc),
        last_message_at=datetime.now(timezone.utc),
        message_count=1,
    )
    assert conversation.contact_id == 1

    msg = Message(
        conversation_id=1,
        contact_id=1,
        wa_message_id="wamid.HBgM123",
        direction="customer",
        body="Hello, is this villa still available?",
        msg_type="text",
        sent_at=datetime.now(timezone.utc),
        meta_status="delivered",
    )
    assert msg.direction == "customer"
    assert msg.wa_message_id == "wamid.HBgM123"

    err = ErrorLog(
        step="n8n",
        error_text="Connection timeout after 3 retries",
        payload={"url": "http://n8n.internal"},
    )
    assert err.step == "n8n"

    user = AppUser(
        email="admin@eurekajo.com",
        password_hash="$2b$12$...",
        role="admin",
        status="active",
    )
    assert user.role == "admin"
