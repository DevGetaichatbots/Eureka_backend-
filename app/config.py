import os
from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator


class Settings(BaseSettings):
    """
    Application Settings defined via Pydantic Settings.
    The app fails fast on startup if any required variable is missing,
    per Technical Build Document Section 5.
    """
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="allow",
        case_sensitive=True,
    )

    # App Runtime
    APP_NAME: str = "WhatsApp Bot & Conversation Viewer"
    APP_ENV: str = "development"
    DEBUG: bool = False
    PORT: int = 8000
    CORS_ORIGINS: str = (
        "http://localhost:3000,http://127.0.0.1:3000,https://eureka-frontend-f0k7.onrender.com"
    )

    # Meta WhatsApp Cloud API (Section 5)
    META_APP_ID: str = "1587149902942521"
    META_APP_SECRET: str = "eureka_meta_secret_test_key"
    META_VERIFY_TOKEN: str = "eureka_webhook_verify_token_2026"
    META_ACCESS_TOKEN: str
    META_PHONE_NUMBER_ID: str
    META_WABA_ID: str
    META_API_VERSION: str = "v21.0"

    # Database & Supabase (Section 4 & 5)
    DATABASE_URL: Optional[str] = None
    SUPABASE_URL: str
    SUPABASE_SERVICE_ROLE_KEY: str
    USE_MOCK_DB: bool = False

    # n8n AI Bot Integration (Section 8)
    N8N_WEBHOOK_URL: str
    N8N_CALLBACK_SECRET: str

    # Security & Viewer Sessions (Section 13)
    SESSION_SECRET: str = "eureka-default-session-secret-key-2026"
    JWT_SECRET_KEY: Optional[str] = None
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # Public Tunnel / App URL (Section 10)
    APP_BASE_URL: str = "https://eureka-backend-6dh0.onrender.com"

    # Error Fallback & Reliability (Section 9)
    FALLBACK_MESSAGE: str = (
        "Sorry, I'm having trouble answering right now. Please try again in a moment."
    )
    WATCHDOG_TIMEOUT_SECONDS: int = 50
    ADMIN_NOTIFICATION_PHONE: Optional[str] = "962790000000"

    # Timezone & Logging (Section 5)
    LOG_LEVEL: str = "INFO"
    TZ: str = "Asia/Karachi"
    CONVERSATION_WINDOW_HOURS: int = 24

    @property
    def cors_origin_list(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def META_GRAPH_API_TOKEN(self) -> str:
        return self.META_ACCESS_TOKEN

    @property
    def FALLBACK_REPLY_TEXT(self) -> str:
        return self.FALLBACK_MESSAGE

    @field_validator("JWT_SECRET_KEY", mode="after")
    @classmethod
    def set_jwt_secret_if_none(cls, v, info):
        # Default JWT_SECRET_KEY to SESSION_SECRET if not explicitly given
        return v or info.data.get("SESSION_SECRET")


try:
    settings = Settings()
except Exception as e:
    print("\n" + "=" * 75)
    print("❌ FATAL: Application failed to start due to missing environment variables!")
    print(f"   Details: {e}")
    print("   Please check your .env file against .env.example.")
    print("=" * 75 + "\n")
    raise
