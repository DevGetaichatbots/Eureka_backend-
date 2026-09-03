import csv
import io
from openpyxl import Workbook
from fastapi import APIRouter, Response, Query, Depends
from datetime import datetime, timezone, timedelta
from app.models.schemas import ContactOut, LeadsSummaryOut
from app.database import db
from app.security import get_current_user_payload

router = APIRouter(prefix="/api", tags=["Leads & CRM Contacts"])


@router.get("/leads", response_model=LeadsSummaryOut)
async def get_leads_summary(user_payload: dict = Depends(get_current_user_payload)):
    """
    Returns summary analytics and contact leads for real estate CRM tracking.
    """
    now = datetime.now(timezone.utc)
    contacts = db.contacts
    message_counts = db.get_message_counts_by_contact()
    active_24h_count = sum(
        1 for c in contacts if (now - c["last_seen_at"]) <= timedelta(hours=24)
    )
    total_messages = sum(message_counts.values())

    leads_out = [
        ContactOut(
            id=c["id"],
            wa_id=c["wa_id"],
            profile_name=c.get("profile_name"),
            first_seen_at=c["first_seen_at"],
            last_seen_at=c["last_seen_at"],
            message_count=message_counts.get(c["id"], 0),
        )
        for c in sorted(contacts, key=lambda x: x["last_seen_at"], reverse=True)
    ]

    return LeadsSummaryOut(
        total_leads=len(contacts),
        active_leads_24h=active_24h_count,
        total_messages=total_messages,
        leads=leads_out,
        items=leads_out,
        total=len(contacts),
        page=1,
        limit=50,
        total_pages=1,
    )


@router.get("/export/leads.csv")
async def export_leads_csv(user_payload: dict = Depends(get_current_user_payload)):
    """
    Streams a UTF-8 CSV file of all contacts for marketing export.
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
    message_counts = db.get_message_counts_by_contact()
    for c in sorted(db.contacts, key=lambda x: x["last_seen_at"], reverse=True):
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
    filename = f"eureka_jo_leads_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/export/leads.xlsx")
async def export_leads_xlsx(user_payload: dict = Depends(get_current_user_payload)):
    """
    Streams an Excel (.xlsx) spreadsheet of all contacts for CRM export.
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
    message_counts = db.get_message_counts_by_contact()
    for c in sorted(db.contacts, key=lambda x: x["last_seen_at"], reverse=True):
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
    filename = f"eureka_jo_leads_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

    return Response(
        content=xlsx_data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
