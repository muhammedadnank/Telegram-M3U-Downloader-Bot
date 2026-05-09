from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URI, DEFAULT_SETTINGS

# ────────────────────────────────────────
# MONGODB SETUP
# ────────────────────────────────────────

mongo_client  = AsyncIOMotorClient(MONGO_URI)
db            = mongo_client["m3u_bot"]
sessions_col  = db["sessions"]
users_col     = db["users"]
downloads_col = db["downloads"]
settings_col  = db["settings"]

# ─────────────────────────────────────────
# DB HELPERS
# ─────────────────────────────────────────

async def save_user(user):
    await users_col.update_one(
        {"user_id": user.id},
        {"$set": {
            "user_id":    user.id,
            "username":   user.username,
            "first_name": user.first_name,
            "last_seen":  datetime.now(timezone.utc),
        }},
        upsert=True
    )

async def save_session(user_id: int, metadata: dict, episodes: list):
    await sessions_col.update_one(
        {"user_id": user_id},
        {"$set": {
            "user_id":    user_id,
            "metadata":   metadata,
            "episodes":   episodes,
            "updated_at": datetime.now(timezone.utc),
        }},
        upsert=True
    )

async def get_session(user_id: int) -> dict | None:
    return await sessions_col.find_one({"user_id": user_id}, {"_id": 0})

async def log_download(user_id: int, episode: dict, fmt: str, quality: str, success: bool):
    await downloads_col.insert_one({
        "user_id":       user_id,
        "title":         episode.get("title"),
        "url":           episode.get("url"),
        "format":        fmt,
        "quality":       quality,
        "success":       success,
        "downloaded_at": datetime.now(timezone.utc),
    })

async def get_settings(user_id: int) -> dict:
    doc = await settings_col.find_one({"user_id": user_id}, {"_id": 0})
    if not doc:
        return DEFAULT_SETTINGS.copy()
    return {**DEFAULT_SETTINGS, **doc}

async def save_settings(user_id: int, patch: dict):
    await settings_col.update_one(
        {"user_id": user_id},
        {"$set": {"user_id": user_id, **patch}},
        upsert=True
    )

