from fastapi import HTTPException, Header
from core.config import db, DEFAULT_SETTINGS


async def get_settings():
    settings = await db.settings.find_one({"key": "global"}, {"_id": 0})
    if not settings:
        await db.settings.insert_one(DEFAULT_SETTINGS.copy())
        settings = DEFAULT_SETTINGS.copy()
    else:
        # Merge in any new default keys not yet in DB
        for k, v in DEFAULT_SETTINGS.items():
            if k not in settings:
                settings[k] = v
    return settings


async def verify_admin(x_admin_token: str = Header(None)):
    if not x_admin_token:
        raise HTTPException(status_code=401, detail="Admin token required")
    settings = await get_settings()
    if x_admin_token != settings.get("admin_password", DEFAULT_SETTINGS["admin_password"]):
        raise HTTPException(status_code=403, detail="Invalid admin credentials")
    return True
