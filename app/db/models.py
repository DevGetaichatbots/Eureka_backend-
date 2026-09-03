from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey,
    CheckConstraint,
    Index,
    func,
    JSON,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Contact(Base):
    """
    contacts table: Represents unique WhatsApp customer contacts by E.164 phone number.
    """
    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    wa_id = Column(String(32), unique=True, nullable=False, index=True)  # E.164 without '+'
    profile_name = Column(String(255), nullable=True)
    first_seen_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    message_count = Column(Integer, default=1, nullable=False)

    # Relationships
    conversations = relationship("Conversation", back_populates="contact", cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="contact", cascade="all, delete-orphan")


class Conversation(Base):
    """
    conversations table: Represents 24-hour windowed conversation sessions.
    """
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    contact_id = Column(Integer, ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False, index=True)
    started_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    last_message_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    message_count = Column(Integer, default=1, nullable=False)

    # Relationships
    contact = relationship("Contact", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_conversations_last_message", last_message_at.desc()),
    )


class Message(Base):
    """
    messages table: Complete chronological transcript of inbound customer & outbound bot messages.
    """
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False, index=True)
    wa_message_id = Column(String(128), unique=True, nullable=True, index=True)  # Meta WAMID for deduplication
    direction = Column(String(16), nullable=False)  # 'customer' | 'bot'
    body = Column(Text, nullable=True)
    msg_type = Column(String(32), default="text", nullable=False)
    media_url = Column(Text, nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=False)
    meta_status = Column(String(32), default="sent", nullable=True)  # sent, delivered, read, failed
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    conversation = relationship("Conversation", back_populates="messages")
    contact = relationship("Contact", back_populates="messages")

    __table_args__ = (
        CheckConstraint("direction IN ('customer', 'bot')", name="check_message_direction"),
        Index("idx_messages_conv_sent_desc", conversation_id, sent_at.desc()),
        Index("idx_messages_contact_sent_desc", contact_id, sent_at.desc()),
    )


class ErrorLog(Base):
    """
    error_log table: Central diagnostic logging for webhook, n8n, Meta API, and database errors.
    """
    __tablename__ = "error_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    wa_id = Column(String(32), nullable=True)
    inbound_body = Column(Text, nullable=True)
    step = Column(String(32), nullable=False)  # 'webhook' | 'n8n' | 'openai' | 'meta_send' | 'db'
    error_text = Column(Text, nullable=False)
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    __table_args__ = (
        Index("idx_error_log_created_at", created_at.desc()),
    )


class AppUser(Base):
    """
    app_users table: Dashboard viewer & administrator accounts.
    """
    __tablename__ = "app_users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(32), default="viewer", nullable=False)  # 'admin' | 'viewer'
    status = Column(String(32), default="active", nullable=False)  # 'active' | 'disabled'
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
