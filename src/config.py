import os
from dotenv import load_dotenv

load_dotenv() # Load variables from .env


def _require(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return val

API_ID       = int(_require("API_ID"))
API_HASH     = _require("API_HASH")
BOT_TOKEN    = _require("BOT_TOKEN")
MONGO_URI    = _require("MONGO_URI")

post_chan = os.environ.get("POST_CHANNEL", "")
if post_chan:
    try:
        POST_CHANNEL = int(post_chan)
    except ValueError:
        POST_CHANNEL = post_chan
else:
    POST_CHANNEL = None
# ─────────────────────────────────────────
# QUALITY OPTIONS
# ─────────────────────────────────────────

QUALITY_OPTIONS = {
    "best":  ("Best",  "bestvideo+bestaudio/best"),
    "960p":  ("960p",  "bestvideo[height<=960]+bestaudio/best[height<=960]"),
    "640p":  ("640p",  "bestvideo[height<=640]+bestaudio/best[height<=640]"),
}

DEFAULT_SETTINGS = {
    "format":            "auto",
    "quality":           "best",
    "channel_post":      False,
    "filename_template": "{title}",
    "auto_download":     False,
}