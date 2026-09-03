import os
import httpx
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from urllib.parse import quote
from app.config import settings


class SupabaseDatabase:
    """
    Production/Staging Supabase PostgREST Database Client.
    Executes live persistent CRUD operations directly against Supabase PostgreSQL.
    """
    def __init__(self):
        self.supabase_url = settings.SUPABASE_URL.rstrip('/')
        self.headers = {
            "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

    def _get_client(self) -> httpx.Client:
        return httpx.Client(base_url=self.supabase_url, headers=self.headers, timeout=10.0)

    # Property getters for compatibility
    @property
    def conversations(self) -> List[Dict[str, Any]]:
        with self._get_client() as client:
            res = client.get("/rest/v1/conversations?select=*&order=last_message_at.desc")
            if res.status_code == 200:
                data = res.json()
                for c in data:
                    c["started_at"] = datetime.fromisoformat(c["started_at"].replace('Z', '+00:00'))
                    c["last_message_at"] = datetime.fromisoformat(c["last_message_at"].replace('Z', '+00:00'))
                return data
        return []

    @property
    def contacts(self) -> List[Dict[str, Any]]:
        with self._get_client() as client:
            res = client.get("/rest/v1/contacts?select=*")
            if res.status_code == 200:
                data = res.json()
                for c in data:
                    c["first_seen_at"] = datetime.fromisoformat(c["first_seen_at"].replace('Z', '+00:00'))
                    c["last_seen_at"] = datetime.fromisoformat(c["last_seen_at"].replace('Z', '+00:00'))
                return data
        return []

    def _parse_message_row(self, m: Dict[str, Any]) -> Dict[str, Any]:
        if m.get("sent_at") and isinstance(m["sent_at"], str):
            m["sent_at"] = datetime.fromisoformat(m["sent_at"].replace("Z", "+00:00"))
        if m.get("created_at") and isinstance(m["created_at"], str):
            m["created_at"] = datetime.fromisoformat(m["created_at"].replace("Z", "+00:00"))
        return m

    def count_messages(self) -> int:
        with self._get_client() as client:
            res = client.get(
                "/rest/v1/messages?select=id",
                headers={"Prefer": "count=exact", "Range": "0-0"},
            )
            content_range = res.headers.get("content-range") or res.headers.get("Content-Range")
            if content_range and "/" in content_range:
                total = content_range.split("/")[-1]
                if total.isdigit():
                    return int(total)
        return len(self.messages)

    def get_message_counts_by_contact(self) -> Dict[int, int]:
        """Actual message rows per contact — same source as the conversation thread."""
        counts: Dict[int, int] = {}
        page_size = 1000
        offset = 0
        with self._get_client() as client:
            while offset < 100000:
                res = client.get(
                    "/rest/v1/messages?select=contact_id",
                    headers={"Range": f"{offset}-{offset + page_size - 1}"},
                )
                if res.status_code not in (200, 206):
                    break
                rows = res.json() or []
                for row in rows:
                    cid = row.get("contact_id")
                    if cid is None:
                        continue
                    cid_int = int(cid)
                    counts[cid_int] = counts.get(cid_int, 0) + 1
                if len(rows) < page_size:
                    break
                offset += page_size
        return counts

    @property
    def messages(self) -> List[Dict[str, Any]]:
        with self._get_client() as client:
            res = client.get(
                "/rest/v1/messages?select=*&order=sent_at.asc,id.asc",
                headers={"Range": "0-9998"},
            )
            if res.status_code in (200, 206):
                return [self._parse_message_row(m) for m in res.json()]
        return []

    def get_messages_for_contact(self, contact_id: int) -> List[Dict[str, Any]]:
        with self._get_client() as client:
            res = client.get(
                f"/rest/v1/messages?contact_id=eq.{contact_id}&select=*&order=id.asc",
                headers={"Range": "0-9998"},
            )
            if res.status_code in (200, 206):
                return [self._parse_message_row(m) for m in res.json()]
        return []

    def get_messages_for_conversation(self, conversation_id: int) -> List[Dict[str, Any]]:
        with self._get_client() as client:
            res = client.get(
                f"/rest/v1/messages?conversation_id=eq.{conversation_id}&select=*&order=id.asc",
                headers={"Range": "0-9998"},
            )
            if res.status_code in (200, 206):
                return [self._parse_message_row(m) for m in res.json()]
        return []

    def get_conversation(self, conversation_id: int) -> Optional[Dict[str, Any]]:
        with self._get_client() as client:
            res = client.get(f"/rest/v1/conversations?id=eq.{conversation_id}&select=*")
            if res.status_code == 200 and res.json():
                conv = res.json()[0]
                conv["started_at"] = datetime.fromisoformat(conv["started_at"].replace("Z", "+00:00"))
                conv["last_message_at"] = datetime.fromisoformat(conv["last_message_at"].replace("Z", "+00:00"))
                return conv
        return None

    def get_contact(self, contact_id: int) -> Optional[Dict[str, Any]]:
        with self._get_client() as client:
            res = client.get(f"/rest/v1/contacts?id=eq.{contact_id}&select=*")
            if res.status_code == 200 and res.json():
                contact = res.json()[0]
                contact["first_seen_at"] = datetime.fromisoformat(contact["first_seen_at"].replace("Z", "+00:00"))
                contact["last_seen_at"] = datetime.fromisoformat(contact["last_seen_at"].replace("Z", "+00:00"))
                return contact
        return None

    def get_latest_message(self, conversation_id: int) -> Optional[Dict[str, Any]]:
        with self._get_client() as client:
            res = client.get(
                f"/rest/v1/messages?conversation_id=eq.{conversation_id}&select=*&order=id.desc&limit=1"
            )
            if res.status_code == 200 and res.json():
                return self._parse_message_row(res.json()[0])
        return None

    def get_latest_messages_map(self) -> Dict[int, Dict[str, Any]]:
        """One query: newest message per conversation_id for the inbox list."""
        latest: Dict[int, Dict[str, Any]] = {}
        with self._get_client() as client:
            res = client.get(
                "/rest/v1/messages?select=*&order=id.desc",
                headers={"Range": "0-499"},
            )
            if res.status_code not in (200, 206):
                return latest
            for row in res.json():
                cid = row.get("conversation_id")
                if cid is None or cid in latest:
                    continue
                latest[cid] = self._parse_message_row(row)
        return latest

    @property
    def error_logs(self) -> List[Dict[str, Any]]:
        with self._get_client() as client:
            res = client.get("/rest/v1/error_log?select=*&order=created_at.desc")
            if res.status_code == 200:
                data = res.json()
                for e in data:
                    e["created_at"] = datetime.fromisoformat(e["created_at"].replace('Z', '+00:00'))
                return data
        return []

    @property
    def app_users(self) -> List[Dict[str, Any]]:
        with self._get_client() as client:
            res = client.get("/rest/v1/app_users?select=*")
            if res.status_code == 200:
                data = res.json()
                for u in data:
                    if u.get("created_at"):
                        u["created_at"] = datetime.fromisoformat(u["created_at"].replace('Z', '+00:00'))
                    if u.get("last_login_at"):
                        u["last_login_at"] = datetime.fromisoformat(u["last_login_at"].replace('Z', '+00:00'))
                return data
        return []

    def get_users_by_email(self, email: str) -> List[Dict[str, Any]]:
        clean = (email or "").strip().lower()
        if not clean:
            return []
        encoded = quote(clean, safe="")
        with self._get_client() as client:
            res = client.get(
                f"/rest/v1/app_users?email=eq.{encoded}&select=*&order=id.desc"
            )
            if res.status_code != 200:
                return []
            data = res.json() or []
            for u in data:
                if u.get("created_at") and isinstance(u["created_at"], str):
                    u["created_at"] = datetime.fromisoformat(u["created_at"].replace("Z", "+00:00"))
                if u.get("last_login_at") and isinstance(u["last_login_at"], str):
                    u["last_login_at"] = datetime.fromisoformat(u["last_login_at"].replace("Z", "+00:00"))
            return data

    def get_user_for_login(self, email: str) -> Optional[Dict[str, Any]]:
        users = self.get_users_by_email(email)
        return users[0] if users else None

    def update_last_login(self, user_id: int) -> None:
        """Persists last_login_at timestamp to Supabase for a user."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._get_client() as client:
            client.patch(
                f"/rest/v1/app_users?id=eq.{user_id}",
                json={"last_login_at": now_iso},
            )

    def create_user(self, email: str, password_hash: str, role: str, status: str = "active") -> Dict[str, Any]:
        """Creates a new app user directly in Supabase."""
        now_iso = datetime.now(timezone.utc).isoformat()
        new_row = {
            "email": email.strip().lower(),
            "password_hash": password_hash,
            "role": role,
            "status": status,
            "created_at": now_iso,
        }
        with self._get_client() as client:
            res = client.post("/rest/v1/app_users", json=[new_row])
            if res.status_code in (200, 201) and res.json():
                created = res.json()[0]
                if created.get("id") is None:
                    raise RuntimeError("User insert returned no id")
                if created.get("created_at"):
                    created["created_at"] = datetime.fromisoformat(created["created_at"].replace('Z', '+00:00'))
                return created
            raise RuntimeError(
                f"Failed to create user in database ({res.status_code}): {res.text[:400]}"
            )

    def update_user(self, user_id: int, update_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Updates user status, role, or other fields in Supabase."""
        with self._get_client() as client:
            res = client.patch(
                f"/rest/v1/app_users?id=eq.{user_id}",
                json=update_data,
            )
            if res.status_code not in (200, 204):
                return None
            payload = []
            try:
                if res.content:
                    payload = res.json()
            except Exception:
                payload = []
            if not payload:
                refetch = client.get(f"/rest/v1/app_users?id=eq.{user_id}&select=*")
                payload = refetch.json() if refetch.status_code == 200 else []
            if not payload:
                return None
            updated = payload[0]
            if updated.get("created_at"):
                updated["created_at"] = datetime.fromisoformat(updated["created_at"].replace('Z', '+00:00'))
            if updated.get("last_login_at"):
                updated["last_login_at"] = datetime.fromisoformat(updated["last_login_at"].replace('Z', '+00:00'))
            return updated
        return None

    def delete_user(self, user_id: int) -> bool:
        """Deletes a user account from Supabase."""
        with self._get_client() as client:
            res = client.delete(f"/rest/v1/app_users?id=eq.{user_id}")
            return res.status_code in (200, 204)

    def update_user_password(self, user_id: int, password_hash: str, email: Optional[str] = None) -> bool:
        """Replace the password hash for this user. If email is set, update every
        duplicate row with that email so old passwords cannot keep working."""
        with self._get_client() as client:
            if email:
                encoded = quote(email.strip().lower(), safe="")
                res = client.patch(
                    f"/rest/v1/app_users?email=eq.{encoded}",
                    json={"password_hash": password_hash},
                )
            else:
                res = client.patch(
                    f"/rest/v1/app_users?id=eq.{user_id}",
                    json={"password_hash": password_hash},
                )
            if res.status_code not in (200, 204):
                return False
            check = client.get(f"/rest/v1/app_users?id=eq.{user_id}&select=password_hash")
            if check.status_code != 200 or not check.json():
                return False
            stored = check.json()[0].get("password_hash")
            return stored == password_hash

    def is_message_duplicate(self, wa_message_id: str) -> bool:
        if not wa_message_id:
            return False
        with self._get_client() as client:
            res = client.get(f"/rest/v1/messages?wa_message_id=eq.{wa_message_id}&select=id")
            if res.status_code == 200 and len(res.json()) > 0:
                return True
        return False

    def mark_message_processed(self, wa_message_id: str):
        pass

    def upsert_contact(self, wa_id: str, profile_name: Optional[str] = None) -> Dict[str, Any]:
        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()
        with self._get_client() as client:
            res = client.get(f"/rest/v1/contacts?wa_id=eq.{wa_id}&select=*")
            if res.status_code == 200 and len(res.json()) > 0:
                contact = res.json()[0]
                update_data = {
                    "last_seen_at": now_iso,
                }
                if profile_name and profile_name.strip():
                    update_data["profile_name"] = profile_name
                up_res = client.patch(
                    f"/rest/v1/contacts?id=eq.{contact['id']}",
                    json=update_data
                )
                res_contact = up_res.json()[0] if (up_res.status_code in (200, 204) and len(up_res.json()) > 0) else contact
                res_contact["first_seen_at"] = datetime.fromisoformat(res_contact["first_seen_at"].replace('Z', '+00:00'))
                res_contact["last_seen_at"] = datetime.fromisoformat(res_contact["last_seen_at"].replace('Z', '+00:00'))
                return res_contact

            new_contact = {
                "wa_id": wa_id,
                "profile_name": profile_name or f"WhatsApp {wa_id[-4:]}",
                "first_seen_at": now_iso,
                "last_seen_at": now_iso,
                "message_count": 1,
            }
            ins_res = client.post("/rest/v1/contacts", json=[new_contact])
            res_contact = ins_res.json()[0] if (ins_res.status_code in (200, 201) and len(ins_res.json()) > 0) else new_contact
            res_contact["first_seen_at"] = datetime.fromisoformat(res_contact["first_seen_at"].replace('Z', '+00:00'))
            res_contact["last_seen_at"] = datetime.fromisoformat(res_contact["last_seen_at"].replace('Z', '+00:00'))
            return res_contact

    def touch_conversation(self, conversation_id: int) -> None:
        """Bump last_message_at so the inbox list and polls see the newest WhatsApp activity."""
        if not conversation_id:
            return
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._get_client() as client:
            client.patch(
                f"/rest/v1/conversations?id=eq.{conversation_id}",
                json={"last_message_at": now_iso},
            )

    def resolve_conversation(
        self,
        contact_id: int,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        now_dt = now or datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()

        with self._get_client() as client:
            res = client.get(
                f"/rest/v1/conversations?contact_id=eq.{contact_id}&order=last_message_at.desc&limit=1"
            )
            if res.status_code == 200 and len(res.json()) > 0:
                conv = res.json()[0]
                update_data = {
                    "last_message_at": now_iso,
                    "message_count": conv.get("message_count", 0) + 1,
                }
                up_res = client.patch(
                    f"/rest/v1/conversations?id=eq.{conv['id']}",
                    json=update_data
                )
                res_conv = up_res.json()[0] if (up_res.status_code in (200, 204) and len(up_res.json()) > 0) else conv
                res_conv["started_at"] = datetime.fromisoformat(res_conv["started_at"].replace('Z', '+00:00'))
                res_conv["last_message_at"] = datetime.fromisoformat(res_conv["last_message_at"].replace('Z', '+00:00'))
                return res_conv

            new_conv = {
                "contact_id": contact_id,
                "started_at": now_iso,
                "last_message_at": now_iso,
                "message_count": 1,
            }
            ins_res = client.post("/rest/v1/conversations", json=[new_conv])
            res_conv = ins_res.json()[0] if (ins_res.status_code in (200, 201) and len(ins_res.json()) > 0) else new_conv
            res_conv["started_at"] = datetime.fromisoformat(res_conv["started_at"].replace('Z', '+00:00'))
            res_conv["last_message_at"] = datetime.fromisoformat(res_conv["last_message_at"].replace('Z', '+00:00'))
            return res_conv

    def insert_message(
        self,
        conversation_id: int,
        contact_id: int,
        direction: str,
        body: str,
        wa_message_id: Optional[str] = None,
        msg_type: str = "text",
        media_url: Optional[str] = None,
        sent_at: Optional[datetime] = None,
        meta_status: str = "sent",
    ) -> Dict[str, Any]:
        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()
        message_timestamp = (sent_at or now_dt).isoformat()
        new_msg = {
            "conversation_id": conversation_id,
            "contact_id": contact_id,
            "wa_message_id": wa_message_id,
            "direction": direction,
            "body": body,
            "msg_type": msg_type,
            "media_url": media_url,
            "sent_at": message_timestamp,
            "meta_status": meta_status,
        }
        with self._get_client() as client:
            ins_res = client.post("/rest/v1/messages", json=[new_msg])
            res_msg = ins_res.json()[0] if (ins_res.status_code in (200, 201) and len(ins_res.json()) > 0) else new_msg
            if "sent_at" in res_msg and isinstance(res_msg["sent_at"], str):
                res_msg["sent_at"] = datetime.fromisoformat(res_msg["sent_at"].replace('Z', '+00:00'))
            if "created_at" in res_msg and isinstance(res_msg["created_at"], str):
                res_msg["created_at"] = datetime.fromisoformat(res_msg["created_at"].replace('Z', '+00:00'))
            self.touch_conversation(conversation_id)
            return res_msg

    def log_error(
        self,
        step: str,
        error_text: str,
        conversation_id: Optional[int] = None,
        wa_id: Optional[str] = None,
        inbound_body: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()
        err_entry = {
            "conversation_id": conversation_id,
            "wa_id": wa_id,
            "inbound_body": inbound_body,
            "step": step,
            "error_text": error_text,
            "payload": payload,
        }
        with self._get_client() as client:
            ins_res = client.post("/rest/v1/error_log", json=[err_entry])
            res_err = ins_res.json()[0] if (ins_res.status_code in (200, 201) and len(ins_res.json()) > 0) else err_entry
            if "created_at" in res_err and isinstance(res_err["created_at"], str):
                res_err["created_at"] = datetime.fromisoformat(res_err["created_at"].replace('Z', '+00:00'))
            return res_err


db = SupabaseDatabase()
