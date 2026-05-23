import uuid
import csv
import io
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

from core.config import db, logger
from routers.auth import _get_current_user
from core.auth import verify_admin

router = APIRouter(prefix="/api")


class SuggestionCreate(BaseModel):
    type: str  # "field" or "general"
    text: str


@router.post("/suggestions")
async def create_suggestion(req: SuggestionCreate, request: Request):
    user = await _get_current_user(request)
    if not user:
        raise HTTPException(401, "Login required to submit suggestions")

    if not req.text.strip():
        raise HTTPException(400, "Suggestion text cannot be empty")

    if req.type not in ("field", "general"):
        raise HTTPException(400, "Type must be 'field' or 'general'")

    suggestion = {
        "suggestion_id": f"sug_{uuid.uuid4().hex[:12]}",
        "user_id": user["user_id"],
        "user_email": user["email"],
        "user_name": user.get("name", ""),
        "type": req.type,
        "text": req.text.strip()[:1000],
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.suggestions.insert_one(suggestion)
    logger.info(f"New {req.type} suggestion from {user['email']}: {req.text[:50]}")

    return {"status": "ok", "suggestion_id": suggestion["suggestion_id"]}


@router.get("/admin/suggestions", dependencies=[Depends(verify_admin)])
async def get_suggestions(request: Request):
    suggestions = await db.suggestions.find(
        {}, {"_id": 0}
    ).sort("created_at", -1).to_list(200)

    return {"suggestions": suggestions}


@router.post("/admin/suggestions/{suggestion_id}/status", dependencies=[Depends(verify_admin)])
async def update_suggestion_status(suggestion_id: str, request: Request):
    body = await request.json()
    new_status = body.get("status", "reviewed")

    result = await db.suggestions.update_one(
        {"suggestion_id": suggestion_id},
        {"$set": {"status": new_status, "reviewed_at": datetime.now(timezone.utc).isoformat()}},
    )
    if result.modified_count == 0:
        raise HTTPException(404, "Suggestion not found")

    return {"status": "ok"}


# ── Contact form (public, no auth) ──

_contact_rate_limit: dict = {}  # {ip: [timestamps]}
CONTACT_RATE_WINDOW = 3600  # 1 hour
CONTACT_RATE_MAX = 5  # max submissions per window


class ContactCreate(BaseModel):
    name: str
    email: str
    message: str
    website: str = ""  # honeypot field — should be empty


@router.post("/contact")
async def create_contact(req: ContactCreate, request: Request):
    # Honeypot check
    if req.website.strip():
        # Bot filled the hidden field — silently accept to not reveal the trap
        return {"status": "ok"}

    if not req.message.strip():
        raise HTTPException(400, "Message cannot be empty")
    if not req.email.strip() or "@" not in req.email:
        raise HTTPException(400, "Valid email is required")

    # Rate limiting by IP
    ip = request.headers.get("x-forwarded-for", request.client.host or "").split(",")[0].strip()
    now = datetime.now(timezone.utc).timestamp()
    timestamps = _contact_rate_limit.get(ip, [])
    timestamps = [t for t in timestamps if now - t < CONTACT_RATE_WINDOW]
    if len(timestamps) >= CONTACT_RATE_MAX:
        raise HTTPException(429, "Too many messages. Please try again later.")
    timestamps.append(now)
    _contact_rate_limit[ip] = timestamps

    doc = {
        "message_id": f"msg_{uuid.uuid4().hex[:12]}",
        "name": req.name.strip()[:200],
        "email": req.email.strip()[:200],
        "message": req.message.strip()[:5000],
        "status": "unread",
        "ip": ip,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.contact_messages.insert_one(doc)
    logger.info(f"New contact message from {req.email.strip()}: {req.message[:50]}")

    return {"status": "ok"}


@router.get("/admin/contact-messages", dependencies=[Depends(verify_admin)])
async def get_contact_messages():
    messages = await db.contact_messages.find(
        {}, {"_id": 0}
    ).sort("created_at", -1).to_list(200)
    return {"messages": messages}


@router.post("/admin/contact-messages/{message_id}/status", dependencies=[Depends(verify_admin)])
async def update_contact_message_status(message_id: str, request: Request):
    body = await request.json()
    new_status = body.get("status", "read")
    result = await db.contact_messages.update_one(
        {"message_id": message_id},
        {"$set": {"status": new_status, "reviewed_at": datetime.now(timezone.utc).isoformat()}},
    )
    if result.modified_count == 0:
        raise HTTPException(404, "Message not found")
    return {"status": "ok"}


@router.get("/admin/users", dependencies=[Depends(verify_admin)])
async def get_users(offset: int = 0, limit: int = 100, page: int = None):
    if page is not None and page > 0:
        offset = (page - 1) * limit
    total = await db.users.count_documents({})
    users = await db.users.find(
        {}, {"_id": 0, "password_hash": 0, "verification_token": 0}
    ).sort("created_at", -1).skip(offset).limit(limit).to_list(limit)
    return {"users": users, "total": total, "offset": offset, "limit": limit}


@router.get("/admin/users/export", dependencies=[Depends(verify_admin)])
async def export_users():
    """Export all users as CSV (name, email, provider, status, registered)."""
    users = await db.users.find(
        {}, {"_id": 0, "password_hash": 0, "verification_token": 0}
    ).sort("created_at", -1).to_list(None)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["name", "email", "provider", "status", "registered"])
    for u in users:
        status = "deactivated" if u.get("active") is False else ("verified" if u.get("email_verified") else "unverified")
        registered = str(u.get("created_at") or "")[:10]
        writer.writerow([u.get("name", ""), u.get("email", ""), u.get("provider", ""), status, registered])

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=kurate_users_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"},
    )
async def user_registrations():
    """Return daily and cumulative user registration counts for charting."""
    from collections import defaultdict
    daily = defaultdict(int)
    async for u in db.users.find(
        {"created_at": {"$exists": True}},
        {"_id": 0, "created_at": 1, "provider": 1}
    ):
        created = u.get("created_at", "")
        if isinstance(created, str) and len(created) >= 10:
            day = created[:10]
            daily[day] += 1
    # Sort and compute cumulative
    sorted_days = sorted(daily.items())
    cumulative = 0
    series = []
    for day, count in sorted_days:
        cumulative += count
        series.append({"date": day, "daily": count, "cumulative": cumulative})
    return {"series": series, "total": cumulative}



@router.post("/admin/users/{user_id}/status", dependencies=[Depends(verify_admin)])
async def update_user_status(user_id: str, request: Request):
    body = await request.json()
    active = body.get("active")
    if active is None:
        raise HTTPException(400, "Missing 'active' field")

    result = await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"active": bool(active)}},
    )
    if result.matched_count == 0:
        raise HTTPException(404, "User not found")

    # If deactivating, clear all their sessions
    if not active:
        await db.user_sessions.delete_many({"user_id": user_id})

    return {"status": "ok", "active": bool(active)}

