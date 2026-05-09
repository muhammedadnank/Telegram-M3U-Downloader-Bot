import os
import tempfile
from pyrogram import Client, filters
from pyrogram.types import Message

from database import save_user, save_session
from utils import parse_m3u, build_episode_keyboard

import json

@Client.on_message(filters.document)
async def handle_document(client: Client, message: Message):
    await save_user(message.from_user)
    doc = message.document
    filename = doc.file_name.lower() if doc.file_name else ""

    if not (filename.endswith(".m3u") or filename.endswith(".json")):
        await message.reply_text("⚠️ Please send a `.m3u` or `.json` file.")
        return

    status = await message.reply_text("⏳ Parsing file...")

    with tempfile.TemporaryDirectory() as tmpdir:
        path = await message.download(file_name=os.path.join(tmpdir, "uploaded_file"))
        
        if filename.endswith(".json"):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            meta = {
                "playlist": data.get("title", "Unknown Playlist"),
                "artist": data.get("author", "Unknown"),
                "cover_url": data.get("cover_url", ""),
                "language": data.get("language", ""),
                "show_type": data.get("show_type", ""),
                "published_on": data.get("published_on", ""),
                "age_rating": data.get("age_rating", ""),
                "description": data.get("description", "")
            }
            episodes = data.get("episodes", [])
        else:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            parsed   = parse_m3u(content)
            episodes = parsed["episodes"]
            meta     = parsed["metadata"]

    if not episodes:
        await status.edit_text("❌ No valid episodes found.")
        return

    await save_session(message.from_user.id, meta, episodes)

    playlist_name = meta.get("playlist", meta.get("album", "Playlist"))
    artist        = meta.get("artist", "Unknown")
    
    caption = f"**{playlist_name}**\n\n"
    caption += f"👤 Author: {artist}\n"
    if meta.get("language"):
        caption += f"🌐 Language: {meta['language']}\n"
    if meta.get("show_type"):
        caption += f"📁 Type: {meta['show_type']}\n"
    caption += f"🎞️ Episodes: {len(episodes)}\n"
    if meta.get("published_on"):
        caption += f"📅 Published: {meta['published_on'][:10]}\n"
    if meta.get("age_rating"):
        caption += f"🔞 Age rating: {meta['age_rating']}\n"
    
    if meta.get("description"):
        desc = meta["description"].strip()
        if len(desc) > 300:
            desc = desc[:300] + "..."
        quoted_desc = "\n".join(f"> __{line}__" for line in desc.split("\n") if line.strip())
        caption += f"\n{quoted_desc}\n"
        
    caption += "\nSelect an episode to download:"

    if meta.get("cover_url"):
        try:
            await message.reply_photo(
                photo=meta["cover_url"],
                caption=caption,
                reply_markup=build_episode_keyboard(episodes, page=0)
            )
            await status.delete()
        except Exception:
            await status.edit_text(caption, reply_markup=build_episode_keyboard(episodes, page=0))
    else:
        await status.edit_text(caption, reply_markup=build_episode_keyboard(episodes, page=0))
