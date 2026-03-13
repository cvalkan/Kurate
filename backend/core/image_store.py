"""Pre-rendered OG image storage and retrieval."""

from core.config import db, logger


async def store_image(key: str, image_bytes: bytes):
    """Store a pre-rendered image in MongoDB."""
    await db.prerendered_images.update_one(
        {"key": key},
        {"$set": {"key": key, "data": image_bytes, "size": len(image_bytes)}},
        upsert=True,
    )


async def get_image(key: str) -> bytes | None:
    """Retrieve a pre-rendered image. Returns None if not found."""
    doc = await db.prerendered_images.find_one({"key": key}, {"_id": 0, "data": 1})
    return doc["data"] if doc else None


async def delete_image(key: str):
    """Delete a pre-rendered image."""
    await db.prerendered_images.delete_one({"key": key})
