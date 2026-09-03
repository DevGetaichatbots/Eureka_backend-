# WhatsApp Bot & Conversation Viewer — Backend Service

FastAPI messaging bridge connecting the Meta WhatsApp Cloud API to the trained n8n AI agent, persisting conversation threads in Supabase PostgreSQL, and serving the internal conversation viewer.

> **Source Spec:** `Technical-Build-Document.pdf` (v1.1)  
> **Tech Stack:** Python 3.11 · FastAPI · Uvicorn · Supabase (PostgreSQL) · n8n · Meta WhatsApp Cloud API  

---

## 🏗️ Repository Architecture

```text
backend/
├── app/
│   ├── main.py              # FastAPI app instance, lifespan & router registration
│   ├── config.py            # Pydantic Settings — strict fail-fast validation
│   ├── deps.py              # Auth, DB, and callback shared-secret guards
│   ├── routers/
│   │   ├── webhook.py       # GET /webhook/whatsapp (handshake) & POST (inbound fast-ack)
│   │   ├── internal.py      # POST /internal/reply (n8n bot callback)
│   │   ├── auth.py          # Session authentication & viewer logins
│   │   ├── conversations.py # Conversation list & full thread transcript
│   │   ├── leads.py         # Leads CRM metrics & CSV/XLSX downloads
│   │   ├── errors.py        # Diagnostic error logs
│   │   └── users.py         # Admin user management
│   ├── services/
│   │   ├── conversation_service.py # 24-hour windowing & message persistence
│   │   ├── meta_service.py         # Meta Cloud API client & send retries
│   │   ├── n8n_service.py          # n8n webhook dispatcher & retries
│   │   └── watchdog.py             # 60-second fallback watchdog timer
│   ├── db/                  # Async database session & models
│   ├── templates/           # Optional Jinja2 templates (if server-rendered)
│   ├── static/              # Static styling assets
│   └── scripts/
│       └── seed_admin.py    # Admin user provisioning script
├── migrations/
│   └── 001_init.sql         # Supabase PostgreSQL schema & performance indexes
├── tests/                   # Automated pytest verification suite
├── .env.example             # Environment variable template (committed)
├── .gitignore               # Strict gitignore (secrets never committed)
├── requirements.txt         # Pinned Python dependencies
└── README.md                # 30-minute setup runbook
```

---

## ⚡ 30-Minute Local Development Setup

Follow this exact sequence to go from a clean clone to a fully operational local bot:

### 1. Clone & Isolate Environment
```bash
git clone <your-repo-url>
cd backend

# Create and activate Python 3.11 virtual environment
python -m venv .venv

# On Linux/macOS:
source .venv/bin/activate
# On Windows PowerShell:
.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env` and supply your project credentials:
```bash
cp .env.example .env
```
Ensure all required variables are populated. The app **refuses to start** if any required key is missing:
* `META_APP_ID`, `META_APP_SECRET`, `META_VERIFY_TOKEN`, `META_ACCESS_TOKEN`, `META_PHONE_NUMBER_ID`, `META_WABA_ID`
* `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`
* `N8N_WEBHOOK_URL`, `N8N_CALLBACK_SECRET`, `SESSION_SECRET`, `APP_BASE_URL`

### 3. Apply Supabase Database Schema
Run `migrations/001_init.sql` directly inside the [Supabase SQL Editor](https://supabase.com/dashboard), or via `psql`:
```bash
psql "$DATABASE_URL" -f migrations/001_init.sql
```
This creates all tables (`contacts`, `conversations`, `messages`, `error_log`, `app_users`) and performance indexes (including the PostgreSQL GIN full-text index).

### 4. Seed the First Admin User
Provision the initial system administrator account:
```bash
python -m app.scripts.seed_admin --email you@company.com --password password123
```

### 5. Start the FastAPI Application
```bash
uvicorn app.main:app --reload --port 8000
```
Verify the health check endpoint:
* Visit `http://localhost:8000/health` $\rightarrow$ should return `{"status": "healthy", "database": "connected"}`.
* Swagger interactive docs: `http://localhost:8000/docs`.

### 6. Expose Localhost to Meta (Tunnel)
Meta WhatsApp Cloud API requires an internet-facing HTTPS URL:
```bash
ngrok http 8000
# Or using cloudflared:
# cloudflared tunnel --url http://localhost:8000
```
Copy your assigned HTTPS tunnel URL (e.g. `https://abc123.ngrok-free.app`):
1. In `.env`: set `APP_BASE_URL=https://abc123.ngrok-free.app`.
2. In the **Meta Developer Dashboard** $\rightarrow$ **WhatsApp** $\rightarrow$ **Configuration**:
   * **Callback URL:** `https://abc123.ngrok-free.app/webhook/whatsapp`
   * **Verify Token:** paste your `META_VERIFY_TOKEN`.
   * Click **Verify and Save** (Meta will immediately send a `GET` handshake).
   * Subscribe to the **`messages`** webhook field.

> ⚠️ **IMPORTANT NOTE ON NGROK:**  
> On free ngrok accounts, the tunnel URL changes on every restart. Each time it changes, update both `APP_BASE_URL` in `.env` and the Callback URL in the Meta Dashboard, or messages will silently stop arriving.

---

## 🧪 Testing the Live Pipeline

1. Send a WhatsApp message to your WhatsApp test number from an approved phone number.
2. Confirm the message flow:
   * Backend logs: Inbound HMAC verified and acknowledged in under 300 ms.
   * Supabase: Inbound row saved in `messages` (`direction='customer'`) under active 24h conversation.
   * n8n receives the dispatch payload at `N8N_WEBHOOK_URL`.
   * n8n posts the reply back to `POST /internal/reply`.
   * Outbound row saved in `messages` (`direction='bot'`) and received on your WhatsApp phone.
3. Open the conversation viewer to monitor live transcripts.

---

## 🔒 Security Requirements
* **Raw Body HMAC**: Webhook HMAC-SHA256 verification is computed strictly on raw bytes before any JSON parsing.
* **Timing-Safe Guards**: All callback secrets and HMAC tokens are compared using constant-time comparison (`hmac.compare_digest`).
* **Credentials**: Never commit `.env`. Service-role keys and database passwords must remain server-side only.
