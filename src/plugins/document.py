import os
import tempfile
import json
from pyrogram import Client, filters
from pyrogram.types import Message

from database import save_user, save_session
from utils import parse_m3u, build_episode_keyboard, parse_json_data, build_caption

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
            meta, episodes = parse_json_data(data)
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
    
    caption = build_caption(meta, episodes)
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
