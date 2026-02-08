import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request, Depends
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


@router.get("/admin/users", dependencies=[Depends(verify_admin)])
async def get_users():
    users = await db.users.find(
        {}, {"_id": 0, "password_hash": 0, "verification_token": 0}
    ).sort("created_at", -1).to_list(500)
    return {"users": users}
