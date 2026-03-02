from fastapi import HTTPException, Header
from core.config import db, DEFAULT_SETTINGS
import hmac
import time

# In-memory cache for settings (avoids DB hit on every request)
_settings_cache = {"data": None, "ts": 0}
_SETTINGS_TTL = 5  # seconds


async def get_settings():
    now = time.time()
    if _settings_cache["data"] and now - _settings_cache["ts"] < _SETTINGS_TTL:
        return _settings_cache["data"].copy()

    settings = await db.settings.find_one({"key": "global"}, {"_id": 0})
    if not settings:
        await db.settings.insert_one(DEFAULT_SETTINGS.copy())
        settings = DEFAULT_SETTINGS.copy()
    else:
        # Merge in any new default keys not yet in DB
        for k, v in DEFAULT_SETTINGS.items():
            if k not in settings:
                settings[k] = v

    _settings_cache["data"] = settings
    _settings_cache["ts"] = now
    return settings


def invalidate_settings_cache():
    """Call after any settings update to force re-read from DB."""
    _settings_cache["data"] = None
    _settings_cache["ts"] = 0


async def verify_admin(x_admin_token: str = Header(None)):
    if not x_admin_token:
        raise HTTPException(status_code=401, detail="Admin token required")
    # Check session tokens in DB (persistent across restarts/pods)
    from routers.admin import _is_valid_session
    if await _is_valid_session(x_admin_token):
        return True
    # Legacy: accept password directly (timing-safe comparison)
    settings = await get_settings()
    stored_pw = settings.get("admin_password", DEFAULT_SETTINGS["admin_password"])
    if hmac.compare_digest(x_admin_token, stored_pw):
        return True
    raise HTTPException(status_code=403, detail="Invalid admin credentials")
