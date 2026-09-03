from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import httpx

from app.config import settings
from app.routers import (
    webhook,
    internal,
    auth,
    conversations,
    leads,
    errors,
    users,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("=" * 70)
    print(f"[STARTUP] {settings.APP_NAME} starting up...")
    print(f"          Environment: {settings.APP_ENV} | Debug: {settings.DEBUG}")
    print(f"          Meta Webhook Handshake: GET /webhook/whatsapp")
    print(f"          Meta Webhook Inbound:   POST /webhook/whatsapp")
    print(f"          n8n Reply Callback:     POST /internal/reply")
    print(f"          Health Check Probe:     GET /health")
    print("=" * 70)
    yield
    print(f"[SHUTDOWN] {settings.APP_NAME} shut down cleanly.")


app = FastAPI(
    title="WhatsApp Bot & Conversation Viewer API",
    description=(
        "FastAPI service connecting Meta WhatsApp Cloud API with n8n AI Bot "
        "and providing the read-only Conversation Viewer & CRM APIs."
    ),
    version="1.1.0",
    lifespan=lifespan,
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=r"https://.*\.onrender\.com",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Routers
app.include_router(webhook.router)
app.include_router(internal.router)
app.include_router(auth.router)
app.include_router(conversations.router)
app.include_router(leads.router)
app.include_router(errors.router)
app.include_router(users.router)


@app.get("/health", tags=["System Health"])
async def health_check():
    """
    Returns 200 plus a DB ping.
    Used by Render health checks and external keep-alive pingers (Section 7 & 12).
    """
    db_status = "connected"
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            res = await client.get(
                f"{settings.SUPABASE_URL.rstrip('/')}/rest/v1/",
                headers={"apikey": settings.SUPABASE_SERVICE_ROLE_KEY},
            )
            if res.status_code >= 500:
                db_status = "degraded"
    except Exception as exc:
        db_status = f"unreachable: {str(exc)}"

    is_healthy = "unreachable" not in db_status and db_status != "degraded"

    return {
        "status": "healthy" if is_healthy else "degraded",
        "database": db_status,
        "service": settings.APP_NAME,
        "environment": settings.APP_ENV,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/", tags=["Root"])
async def root():
    return {
        "name": settings.APP_NAME,
        "status": "online",
        "docs_url": "/docs",
        "health_check": "/health",
    }
