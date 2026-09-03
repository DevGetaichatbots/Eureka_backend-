from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List, Dict, Any, Generic, TypeVar
from datetime import datetime

T = TypeVar("T")


# ==============================================================================
# Meta WhatsApp Cloud API Webhook Schemas
# ==============================================================================

class MetaWebhookVerification(BaseModel):
    hub_mode: str = Field(alias="hub.mode")
    hub_verify_token: str = Field(alias="hub.verify_token")
    hub_challenge: str = Field(alias="hub.challenge")


class MetaMessageAuthor(BaseModel):
    wa_id: str
    profile: Optional[Dict[str, str]] = None


class MetaInboundText(BaseModel):
    body: str


class MetaInboundMedia(BaseModel):
    id: str
    mime_type: Optional[str] = None
    sha256: Optional[str] = None
    caption: Optional[str] = None


class MetaInboundMessage(BaseModel):
    id: str
    from_: str = Field(alias="from")
    timestamp: str
    type: str = "text"
    text: Optional[MetaInboundText] = None
    image: Optional[MetaInboundMedia] = None
    audio: Optional[MetaInboundMedia] = None
    document: Optional[MetaInboundMedia] = None


class MetaWebhookValue(BaseModel):
    messaging_product: str
    metadata: Dict[str, Any]
    contacts: Optional[List[Dict[str, Any]]] = None
    messages: Optional[List[Dict[str, Any]]] = None
    statuses: Optional[List[Dict[str, Any]]] = None


class MetaWebhookChange(BaseModel):
    field: str
    value: Dict[str, Any]


class MetaWebhookEntry(BaseModel):
    id: str
    changes: List[MetaWebhookChange]


class MetaWebhookPayload(BaseModel):
    object: str
    entry: List[MetaWebhookEntry]


# ==============================================================================
# n8n Integration Contracts
# ==============================================================================

class N8NDispatchPayload(BaseModel):
    """Payload dispatched to n8n webhook workflow matching Section 8 & live n8n workflow"""
    conversation_id: int
    wa_id: str
    sessionId: Optional[str] = None
    profile_name: Optional[str] = None
    message: Optional[str] = None
    message_body: Optional[str] = None
    message_id: Optional[str] = None
    wa_message_id: Optional[str] = None
    callback_url: Optional[str] = None
    leadData: Optional[str] = ""
    msg_type: str = "text"
    media_url: Optional[str] = None
    timestamp: Optional[str] = None

    def model_post_init(self, __context: Any) -> None:
        if not self.sessionId:
            self.sessionId = self.wa_id
        if not self.message and self.message_body:
            self.message = self.message_body
        elif not self.message_body and self.message:
            self.message_body = self.message
        if not self.message_id and self.wa_message_id:
            self.message_id = self.wa_message_id
        elif not self.wa_message_id and self.message_id:
            self.wa_message_id = self.message_id


class N8NReplyCallback(BaseModel):
    """Callback payload received from n8n at POST /internal/reply per Section 9"""
    to_wa_id: Optional[str] = None
    wa_id: Optional[str] = None
    reply_text: Optional[str] = None
    text: Optional[str] = None
    conversation_id: int
    status: str = "ok"  # 'ok' | 'error'
    error_message: Optional[str] = None
    reply_to_wa_message_id: Optional[str] = None

    @property
    def resolved_wa_id(self) -> str:
        return self.wa_id or self.to_wa_id or ""

    @property
    def resolved_text(self) -> str:
        return self.text or self.reply_text or ""


# ==============================================================================
# Domain & Database Models (Conversations & Viewer)
# ==============================================================================

class ContactOut(BaseModel):
    id: int
    wa_id: str
    profile_name: Optional[str] = None
    first_seen_at: datetime
    last_seen_at: datetime
    message_count: int


class MessageOut(BaseModel):
    id: int
    conversation_id: int
    contact_id: int
    wa_message_id: Optional[str] = None
    direction: str  # 'customer' | 'bot'
    body: Optional[str] = None
    msg_type: str = "text"  # 'text' | 'image' | 'audio' | 'document'
    media_url: Optional[str] = None
    sent_at: datetime
    meta_status: Optional[str] = "sent"
    created_at: datetime


class ConversationOut(BaseModel):
    id: int
    contact_id: int
    contact: Optional[ContactOut] = None
    started_at: datetime
    last_message_at: datetime
    message_count: int
    last_message: Optional[MessageOut] = None


class ConversationDetailOut(BaseModel):
    conversation: ConversationOut
    messages: List[MessageOut]


class MessageSearchResultOut(BaseModel):
    message: MessageOut
    conversation_id: int
    contact: Optional[ContactOut] = None


class ErrorLogOut(BaseModel):
    id: int
    conversation_id: Optional[int] = None
    wa_id: Optional[str] = None
    inbound_body: Optional[str] = None
    step: str  # 'webhook' | 'n8n' | 'openai' | 'meta_send' | 'db'
    error_text: str
    payload: Optional[Dict[str, Any]] = None
    created_at: datetime


class PaginatedResponse(BaseModel, Generic[T]):
    items: List[T]
    total: int
    page: int
    limit: int
    total_pages: int


class LeadsSummaryOut(BaseModel):
    total_leads: int
    active_leads_24h: int
    total_messages: int
    leads: List[ContactOut]
    items: List[ContactOut] = []
    total: int = 0
    page: int = 1
    limit: int = 50
    total_pages: int = 1


# ==============================================================================
# Authentication & User Management
# ==============================================================================

class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    role: str  # 'admin' | 'viewer'
    status: str  # 'active' | 'disabled'
    created_at: datetime
    last_login_at: Optional[datetime] = None


class LoginResponse(BaseModel):
    success: bool = True
    user: UserOut
    token: str
    message: str = "Authentication successful"


class CreateUserRequest(BaseModel):
    email: EmailStr
    password: str
    role: str = "viewer"


class UpdateUserStatusRequest(BaseModel):
    status: str  # 'active' | 'disabled'


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

