"""Shared auth utilities — keeps circular imports out of core/auth.py and routers/admin.py."""

from core.config import db


async def is_valid_admin_session(token: str) -> bool:
    """Check if an admin session token exists in the DB."""
    doc = await db.admin_sessions.find_one({"key": "sessions", "tokens": token})
    return doc is not None
