-- ==============================================================================
-- Migration: 001_init.sql
-- Project: Eureka Jo WhatsApp Bot & Conversation Viewer
-- Description: Core schema for Contacts, Conversations, Messages, Logs, and App Users
-- ==============================================================================

-- 1. Contacts Table
create table if not exists contacts (
  id bigserial primary key,
  wa_id text unique not null,               -- E.164 without '+', e.g. '962790000000'
  profile_name text,                        -- WhatsApp profile name
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  message_count integer not null default 0
);

-- Index for phone lookups
create index if not exists idx_contacts_wa_id on contacts(wa_id);
create index if not exists idx_contacts_last_seen on contacts(last_seen_at desc);

-- 2. Conversations Table (24-Hour Messaging Session Window)
create table if not exists conversations (
  id bigserial primary key,
  contact_id bigint not null references contacts(id) on delete cascade,
  started_at timestamptz not null default now(),
  last_message_at timestamptz not null default now(),
  message_count integer not null default 0
);

-- Indexes for conversations
create index if not exists idx_conversations_contact_id on conversations(contact_id);
create index if not exists idx_conversations_last_message on conversations(last_message_at desc);

-- 3. Messages Table
create table if not exists messages (
  id bigserial primary key,
  conversation_id bigint not null references conversations(id) on delete cascade,
  contact_id bigint not null references contacts(id) on delete cascade,
  wa_message_id text unique,                -- Meta WhatsApp message ID (idempotency key)
  direction text not null check (direction in ('customer', 'bot')),
  body text,                                -- Plaintext message transcript
  msg_type text not null default 'text',    -- 'text', 'image', 'audio', 'document'
  media_url text,                           -- S3/Supabase storage or Meta media URL
  sent_at timestamptz not null default now(),
  meta_status text default 'sent',          -- 'sent', 'delivered', 'read', 'failed'
  created_at timestamptz not null default now()
);

-- Indexes for messages
create index if not exists idx_messages_conv_sent_desc on messages(conversation_id, sent_at desc);
create index if not exists idx_messages_contact_sent_desc on messages(contact_id, sent_at desc);
create index if not exists idx_messages_body_gin on messages using gin (to_tsvector('english', coalesce(body, '')));
create index if not exists idx_messages_wa_id on messages(wa_message_id);
create index if not exists idx_messages_direction on messages(direction);

-- 4. Diagnostic Error Log Table
create table if not exists error_log (
  id bigserial primary key,
  conversation_id bigint references conversations(id) on delete set null,
  wa_id text,
  inbound_body text,
  step text not null,                       -- 'webhook', 'n8n', 'openai', 'meta_send', 'db'
  error_text text not null,
  payload jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_error_log_step on error_log(step);
create index if not exists idx_error_log_created_at on error_log(created_at desc);

-- 5. Application Users (Conversation Viewer & Admin Portal)
create table if not exists app_users (
  id bigserial primary key,
  email text unique not null,
  password_hash text not null,              -- bcrypt hash
  role text not null default 'viewer' check (role in ('admin', 'viewer')),
  status text not null default 'active' check (status in ('active', 'disabled')),
  created_at timestamptz not null default now(),
  last_login_at timestamptz
);

create index if not exists idx_app_users_email on app_users(email);

-- 6. Default Admin Seed User
-- Email: admin@eurekajo.com
-- Password: password123 ($2b$12$e8xL4sBf0M1c6I6zQ2F2e.qFzX1w2G4m7h0K3p5o9t1r2e3w4q5)
insert into app_users (email, password_hash, role, status)
values (
  'admin@eurekajo.com',
  '$2b$12$lzQ3d6vUqM0g1sVb0E4Oa.n7T9j5kL3q7w0M1n3p5r7t9v1x3z5y7',
  'admin',
  'active'
)
on conflict (email) do nothing;
