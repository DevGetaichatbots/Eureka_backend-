import argparse
import sys
import json
import urllib.request
import urllib.error
from app.config import settings
from app.security import get_password_hash


def seed_admin(email: str, password: str = "password123"):
    print(f"Creating / updating admin user: {email}...")
    password_hash = get_password_hash(password)

    # PostgREST upsert requires on_conflict query parameter for non-PK unique constraint
    url = f"{settings.SUPABASE_URL.rstrip('/')}/rest/v1/app_users?on_conflict=email"
    headers = {
        "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=representation",
    }

    payload = [
        {
            "email": email,
            "password_hash": password_hash,
            "role": "admin",
            "status": "active",
        }
    ]

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print(f"[OK] Admin user seeded successfully:")
            print(f"     Email: {email}")
            print(f"     Role:  admin")
            print(f"     Status: active")
            return data
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="ignore")
        print(f"[ERROR] Failed to seed user ({e.code}): {error_body}")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed first admin user into Supabase app_users table")
    parser.add_argument("--email", type=str, default="admin@eurekajo.com", help="Email for the admin user")
    parser.add_argument("--password", type=str, default="password123", help="Password for the admin user")
    args = parser.parse_args()

    seed_admin(args.email, args.password)
