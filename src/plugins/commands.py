import os
import json
import tempfile
from collections import deque
from pyrogram.errors import UserNotParticipant

from pyrogram import Client, filters
from pyrogram.types import Message

from database import save_user, downloads_col, get_settings, get_session, save_session, save_settings
from state import cancel_events, queue_items, merge_selections
from config import POST_CHANNEL, QUALITY_OPTIONS
from utils import (
    build_settings_keyboard, build_merge_select_keyboard, 
    parse_tg_link, build_scan_confirm_keyboard, build_scan_pick_keyboard,
    parse_json_data, build_caption
)
from engine import enqueue_download


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

# ─────────────────────────────────────────
# SCAN COMMAND
# ─────────────────────────────────────────

async def fetch_json_in_range(client: Client, chat_id: int | str, start: int, end: int) -> list[Message]:
    json_messages = []
    ids = list(range(start, end + 1))
    for i in range(0, len(ids), 100):
        batch = ids[i:i+100]
        msgs = await client.get_messages(chat_id, batch)
        for m in msgs:
            if m.document and m.document.file_name and m.document.file_name.lower().endswith(".json"):
                json_messages.append(m)
    return json_messages

@Client.on_message(filters.command("scan"))
async def cmd_scan(client: Client, message: Message):
    await save_user(message.from_user)
    
    text = message.text or ""
    if text.startswith("/scan"):
        args = text.split()[1:]
        if not args:
            await message.reply_text("❌ Please provide a Telegram channel link.\nExample: `/scan https://t.me/c/123/45`")
            return
        link = args[0]
        fmt_override = None
        qual_override = None
        for arg in args[1:]:
            arg_l = arg.lower()
            if arg_l in ["auto", "mp3", "mp4"]: fmt_override = arg_l
            elif arg_l in QUALITY_OPTIONS: qual_override = arg_l
    else:
        link = text.strip()
        fmt_override = None
        qual_override = None

    parsed_link = parse_tg_link(link)

    
    if not parsed_link:
        await message.reply_text("❌ Invalid Telegram link format. Use format: t.me/c/ID/MSG or t.me/c/ID/START-END")
        return
        
    chat_id = parsed_link["chat_id"]
    msg_start = parsed_link["msg_start"]
    msg_end = parsed_link["msg_end"]
    is_range = parsed_link["is_range"]
    
    s = await get_settings(message.from_user.id)
    fmt = fmt_override if fmt_override else s["format"]
    qual = qual_override if qual_override else s["quality"]
    
    if fmt != s["format"] or qual != s["quality"]:
        await save_settings(message.from_user.id, {"format": fmt, "quality": qual})

    
    status = await message.reply_text("⏳ Scanning message(s)...")
    
    try:
        if is_range:
            if msg_end < msg_start:
                await status.edit_text("❌ Invalid range: end must be greater than start")
                return
            if msg_end - msg_start > 500:
                await status.edit_text("⚠️ Range too large. Scanning first 500 messages only.")
                msg_end = msg_start + 500
                
            json_messages = await fetch_json_in_range(client, chat_id, msg_start, msg_end)
            
            if not json_messages:
                await status.edit_text(f"❌ No JSON files found in messages {msg_start}–{msg_end}")
                return
                
            if len(json_messages) > 1:
                # Show pick UI
                await status.edit_text(
                    f"🔍 Found {len(json_messages)} JSON files in range {msg_start}–{msg_end}.\nSelect one to parse:",
                    reply_markup=build_scan_pick_keyboard(json_messages)
                )
                return
            else:
                msg = json_messages[0]
        else:
            msg = await client.get_messages(chat_id, msg_start)
            if not msg or not msg.document or not msg.document.file_name.lower().endswith(".json"):
                await status.edit_text("❌ No valid `.json` document found in that message.")
                return
                
    except UserNotParticipant:
        await status.edit_text("❌ Bot needs to be added to that channel first.")
        return
    except Exception as e:
        await status.edit_text(f"❌ Error fetching message: {e}")
        return

    await process_json_message(client, message.from_user.id, msg, status)

async def process_json_message(client: Client, user_id: int, json_msg: Message, status: Message):
    await status.edit_text("⏳ Downloading `.json` file...")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        path = await client.download_media(json_msg.document, file_name=os.path.join(tmpdir, "uploaded_file.json"))
        
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            meta, episodes = parse_json_data(data)
        except Exception:
            await status.edit_text("❌ Could not parse JSON. Is it a valid show export?")
            return
            
    if not episodes:
        await status.edit_text("❌ No valid episodes found in the JSON.")
        return
        
    await save_session(user_id, meta, episodes)
    s = await get_settings(user_id)
    
    if s.get("auto_download"):
        fmt = s["format"]
        qual = s["quality"]
        for ep in episodes:
            await enqueue_download(client, status, ep, fmt, qual, user_id, meta, silent=True)
        await status.edit_text(f"🚀 **Full Auto**: Enqueued {len(episodes)} episodes!")
        return

    caption = build_caption(meta, episodes)
    
    if POST_CHANNEL:

        try:
            if meta.get("cover_url"):
                await client.send_photo(
                    chat_id=POST_CHANNEL,
                    photo=meta["cover_url"],
                    caption=caption,
                    reply_markup=build_scan_confirm_keyboard(len(episodes))
                )
            else:
                await client.send_message(
                    chat_id=POST_CHANNEL,
                    text=caption,
                    reply_markup=build_scan_confirm_keyboard(len(episodes))
                )
            await status.delete()
        except Exception as e:
            await status.edit_text(
                f"⚠️ Could not post to channel: {e}\n\n{caption}", 
                reply_markup=build_scan_confirm_keyboard(len(episodes))
            )
    else:
        if meta.get("cover_url"):
            try:
                await client.send_photo(
                    chat_id=user_id,
                    photo=meta["cover_url"],
                    caption=caption,
                    reply_markup=build_scan_confirm_keyboard(len(episodes))
                )
                await status.delete()
            except Exception:
                await status.edit_text(caption, reply_markup=build_scan_confirm_keyboard(len(episodes)))
        else:
            await status.edit_text(caption, reply_markup=build_scan_confirm_keyboard(len(episodes)))