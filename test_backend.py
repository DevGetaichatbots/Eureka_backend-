"""
Automated unit verification script for Eureka Jo FastAPI Backend
"""

import hmac
import hashlib
from app.config import settings
from app.security import verify_meta_signature, verify_n8n_secret, create_access_token, decode_access_token
from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_health():
    res = client.get("/health")
    assert res.status_code == 200, f"Health check failed: {res.text}"
    data = res.json()
    assert data["status"] == "healthy"
    print("[PASS] Health check")


def test_meta_webhook_handshake():
    token = settings.META_VERIFY_TOKEN
    challenge = "1155998822"
    res = client.get(f"/webhook/whatsapp?hub.mode=subscribe&hub.verify_token={token}&hub.challenge={challenge}")
    assert res.status_code == 200, f"Handshake failed: {res.text}"
    assert res.text == challenge, f"Expected {challenge}, got {res.text}"
    print("[PASS] Meta webhook GET handshake")


def test_meta_signature_verification():
    secret = settings.META_APP_SECRET
    body = b'{"test": "payload"}'
    computed_hmac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    valid_header = f"sha256={computed_hmac}"
    assert verify_meta_signature(body, valid_header) is True
    assert verify_meta_signature(body, "sha256=invalid_hash") is False
    print("[PASS] HMAC SHA-256 verification algorithm")


def test_jwt_auth():
    payload = {"sub": "1", "email": "admin@eurekajo.com", "role": "admin"}
    token = create_access_token(payload)
    decoded = decode_access_token(token)
    assert decoded["email"] == "admin@eurekajo.com"
    print("[PASS] JWT creation and decoding")


def test_conversations_api():
    res = client.get("/api/conversations")
    assert res.status_code == 200, f"List conversations failed: {res.text}"
    data = res.json()
    assert "items" in data
    assert len(data["items"]) > 0
    print(f"[PASS] Conversations API ({len(data['items'])} conversations loaded)")


def test_leads_csv_export():
    res = client.get("/api/export/leads.csv")
    assert res.status_code == 200
    assert "text/csv" in res.headers["content-type"]
    assert "Contact ID" in res.text
    print("[PASS] Leads CSV export")


if __name__ == "__main__":
    print("\n--- Running Eureka Jo FastAPI Backend Verification ---")
    test_health()
    test_meta_webhook_handshake()
    test_meta_signature_verification()
    test_jwt_auth()
    test_conversations_api()
    test_leads_csv_export()
    print("--- ALL BACKEND CHECKS PASSED ---\n")
