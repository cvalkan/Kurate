from fastapi import HTTPException, Header
from core.config import db, DEFAULT_SETTINGS


async def get_settings():
    settings = await db.settings.find_one({"key": "global"}, {"_id": 0})
    if not settings:
        await db.settings.insert_one(DEFAULT_SETTINGS.copy())
        settings = DEFAULT_SETTINGS.copy()
    else:
        for k, v in DEFAULT_SETTINGS.items():
            if k not in settings:
                settings[k] = v
    return settings


async def verify_admin(x_admin_token: str = Header(None)):
    if not x_admin_token:
        raise HTTPException(status_code=401, detail="Admin token required")
    from routers.admin import _is_valid_session
    if await _is_valid_session(x_admin_token):
        return True
    raise HTTPException(status_code=403, detail="Invalid admin credentials")
