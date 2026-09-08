import csv
import io
from openpyxl import Workbook
from fastapi import APIRouter, Response, Query, Depends
from datetime import datetime, timezone, timedelta
from typing import Optional
from app.models.schemas import ContactOut, LeadsSummaryOut
from app.database import db
from app.security import get_current_user_payload

router = APIRouter(prefix="/api", tags=["Leads & CRM Contacts"])


def filter_contacts(contacts, q: Optional[str] = None, from_date: Optional[str] = None, to_date: Optional[str] = None):
    res = contacts
    if q:
        q_lower = q.strip().lower()
        digits = "".join(filter(str.isdigit, q_lower))
        res = [
            c for c in res
            if (c.get("profile_name") and q_lower in c["profile_name"].lower())
            or (digits and digits in str(c.get("wa_id", "")))
        ]

    if from_date:
        try:
            from_dt = datetime.fromisoformat(from_date).replace(tzinfo=timezone.utc)
            res = [c for c in res if c["last_seen_at"] >= from_dt or c["first_seen_at"] >= from_dt]
        except Exception:
            pass

    if to_date:
        try:
            to_dt = datetime.fromisoformat(to_date).replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
            res = [c for c in res if c["last_seen_at"] <= to_dt or c["first_seen_at"] <= to_dt]
        except Exception:
            pass

    return res


@router.get("/leads", response_model=LeadsSummaryOut)
async def get_leads_summary(
    q: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    user_payload: dict = Depends(get_current_user_payload),
):
    """
    Returns summary analytics and contact leads for real estate CRM tracking with date filtering.
    """
    now = datetime.now(timezone.utc)
    all_contacts = db.contacts
    filtered = filter_contacts(all_contacts, q=q, from_date=from_date, to_date=to_date)

    message_counts = db.get_message_counts_by_contact()
    active_24h_count = sum(
        1 for c in filtered if (now - c["last_seen_at"]) <= timedelta(hours=24)
    )
    total_messages = sum(message_counts.get(c["id"], 0) for c in filtered)

    sorted_leads = sorted(filtered, key=lambda x: x["last_seen_at"], reverse=True)
    start_idx = (page - 1) * limit
    paged_leads = sorted_leads[start_idx : start_idx + limit]

    leads_out = [
        ContactOut(
            id=c["id"],
            wa_id=c["wa_id"],
            profile_name=c.get("profile_name"),
            first_seen_at=c["first_seen_at"],
            last_seen_at=c["last_seen_at"],
            message_count=message_counts.get(c["id"], 0),
        )
        for c in paged_leads
    ]

    total_pages = max(1, (len(filtered) + limit - 1) // limit)

    return LeadsSummaryOut(
        total_leads=len(filtered),
        active_leads_24h=active_24h_count,
        total_messages=total_messages,
        leads=leads_out,
        items=leads_out,
        total=len(filtered),
        page=page,
        limit=limit,
        total_pages=total_pages,
    )


@router.get("/export/leads.csv")
async def export_leads_csv(
    q: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    user_payload: dict = Depends(get_current_user_payload),
):
    """
    Streams a UTF-8 CSV file of filtered contacts for marketing export.
    """
    output = io.StringIO()
    writer = csv.writer(output)

    # Header row
    writer.writerow([
        "Contact ID",
        "Phone (E.164)",
        "Profile Name",
        "First Contact Date (UTC)",
        "Last Activity Date (UTC)",
        "Total Messages",
        "24h Window Status",
    ])

    now = datetime.now(timezone.utc)
    all_contacts = db.contacts
    filtered = filter_contacts(all_contacts, q=q, from_date=from_date, to_date=to_date)
    message_counts = db.get_message_counts_by_contact()

    for c in sorted(filtered, key=lambda x: x["last_seen_at"], reverse=True):
        is_active = (now - c["last_seen_at"]) <= timedelta(hours=24)
        writer.writerow([
            c["id"],
            f"+{c['wa_id']}",
            c.get("profile_name", "Unknown"),
            c["first_seen_at"].isoformat(),
            c["last_seen_at"].isoformat(),
            message_counts.get(c["id"], 0),
            "Active" if is_active else "Closed",
        ])

    csv_data = output.getvalue()
    label = f"{from_date}_to_{to_date}" if from_date and to_date else datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"eureka_jo_leads_{label}.csv"

    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/export/leads.xlsx")
async def export_leads_xlsx(
    q: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    user_payload: dict = Depends(get_current_user_payload),
):
    """
    Streams an Excel (.xlsx) spreadsheet of filtered contacts for CRM export.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Leads & Contacts"

    # Header row
    ws.append([
        "Contact ID",
        "Phone (E.164)",
        "Profile Name",
        "First Contact Date (UTC)",
        "Last Activity Date (UTC)",
        "Total Messages",
        "24h Window Status",
    ])

    now = datetime.now(timezone.utc)
    all_contacts = db.contacts
    filtered = filter_contacts(all_contacts, q=q, from_date=from_date, to_date=to_date)
    message_counts = db.get_message_counts_by_contact()

    for c in sorted(filtered, key=lambda x: x["last_seen_at"], reverse=True):
        is_active = (now - c["last_seen_at"]) <= timedelta(hours=24)
        ws.append([
            c["id"],
            f"+{c['wa_id']}",
            c.get("profile_name", "Unknown"),
            c["first_seen_at"].isoformat(),
            c["last_seen_at"].isoformat(),
            message_counts.get(c["id"], 0),
            "Active" if is_active else "Closed",
        ])

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    xlsx_data = output.getvalue()
    label = f"{from_date}_to_{to_date}" if from_date and to_date else datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"eureka_jo_leads_{label}.xlsx"

    return Response(
        content=xlsx_data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
