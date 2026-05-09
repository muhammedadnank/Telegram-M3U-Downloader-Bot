from collections import deque

from pyrogram import Client, filters
from pyrogram.types import Message

from database import save_user, downloads_col, get_settings, get_session
from state import cancel_events, queue_items, merge_selections
from utils import build_settings_keyboard, build_merge_select_keyboard

# ─────────────────────────────────────────
# COMMAND HANDLERS
# ─────────────────────────────────────────

@Client.on_message(filters.command("start"))
async def cmd_start(client: Client, message: Message):
    await save_user(message.from_user)
    await message.reply_text(
        "👋 **M3U Downloader Bot**\n\n"
        "📁 Send me a `.m3u` playlist file\n"
        "Download as **MP3** or **MP4**, or merge multiple episodes!\n\n"
        "Commands:\n"
        "/settings — format, quality, filename\n"
        "/queue — pending downloads\n"
        "/cancel — cancel active download\n"
        "/history — last 10 downloads\n"
        "/merge — merge episodes (also available after sending .m3u)\n\n"
        "⚡ Powered by `yt-dlp` + `ffmpeg`"
    )

@Client.on_message(filters.command("history"))
async def cmd_history(client: Client, message: Message):
    await save_user(message.from_user)
    user_id = message.from_user.id
    cursor  = downloads_col.find(
        {"user_id": user_id},
        {"_id": 0, "title": 1, "format": 1, "quality": 1, "success": 1, "downloaded_at": 1}
    ).sort("downloaded_at", -1).limit(10)

    docs = await cursor.to_list(length=10)
    if not docs:
        await message.reply_text("📭 No download history found.")
        return

    lines = ["📜 **Your Last 10 Downloads:**\n"]
    for d in docs:
        status = "✅" if d["success"] else "❌"
        date   = d["downloaded_at"].strftime("%d %b %Y %H:%M")
        qual   = d.get("quality", "best")
        lines.append(f"{status} `{d['title']}` — {d['format'].upper()} {qual} — {date}")
    await message.reply_text("\n".join(lines))

@Client.on_message(filters.command("cancel"))
async def cmd_cancel(client: Client, message: Message):
    user_id = message.from_user.id
    event   = cancel_events.get(user_id)
    if event:
        event.set()
        await message.reply_text("🚫 Cancelling current download...")
    else:
        await message.reply_text("Nothing is downloading right now.")

@Client.on_message(filters.command("queue"))
async def cmd_queue(client: Client, message: Message):
    user_id = message.from_user.id
    q       = queue_items.get(user_id, deque())
    if not q:
        await message.reply_text("📭 Your queue is empty.")
        return
    lines = [f"📋 **Queue ({len(q)} pending):**\n"]
    for i, job in enumerate(q, 1):
        lines.append(f"{i}. `{job['episode']['title']}` — {job['fmt'].upper()} {job['quality']}")
    await message.reply_text("\n".join(lines))

@Client.on_message(filters.command("settings"))
async def cmd_settings(client: Client, message: Message):
    await save_user(message.from_user)
    s = await get_settings(message.from_user.id)
    await message.reply_text("⚙️ **Settings**\nTap to change:", reply_markup=build_settings_keyboard(s))

@Client.on_message(filters.command("merge"))
async def cmd_merge(client: Client, message: Message):
    user_id = message.from_user.id
    session = await get_session(user_id)
    if not session:
        await message.reply_text("⚠️ Send a `.m3u` file first.")
        return
    episodes = session["episodes"]
    merge_selections[user_id] = set()
    await message.reply_text(
        "🔀 **Merge Mode** — Select episodes to merge:",
        reply_markup=build_merge_select_keyboard(episodes, set(), page=0)
    )