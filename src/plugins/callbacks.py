import asyncio
from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, Message

from database import get_session, get_settings, save_settings
from state import (
    cancel_events, merge_selections, active_tasks, 
    awaiting_filename, FMT_CYCLE, QUAL_CYCLE
)
from utils import (
    format_duration, detect_format, build_episode_keyboard,
    build_format_keyboard, build_quality_keyboard, build_merge_select_keyboard,
    build_merge_type_keyboard, build_settings_keyboard
)
from engine import enqueue_download, run_merge

# ─────────────────────────────────────────
# CALLBACK HANDLER
# ─────────────────────────────────────────

@Client.on_callback_query()
async def handle_callback(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    data    = callback.data

    if data.startswith("set:"):
        await handle_settings_callback(client, callback, user_id, data)
        return

    if data.startswith("merge:") or data.startswith("msel:") or data.startswith("mpage:"):
        await handle_merge_callback(client, callback, user_id, data)
        return

    if data.startswith("scan:") or data.startswith("scan_pick:"):
        await handle_scan_callback(client, callback, user_id, data)
        return

    session = await get_session(user_id)
    if not session:
        await callback.answer("❌ Session expired. Send the M3U file again.", show_alert=True)
        return

    episodes = session["episodes"]
    meta     = session["metadata"]

    if data.startswith("page:"):
        page = int(data.split(":")[1])
        await callback.message.edit_text(
            f"📀 **{meta.get('playlist', 'Playlist')}** — Select episode:",
            reply_markup=build_episode_keyboard(episodes, page=page)
        )
        await callback.answer()

    elif data.startswith("back:"):
        page = int(data.split(":")[1])
        await callback.message.edit_text(
            f"📀 **{meta.get('playlist', 'Playlist')}** — Select episode:",
            reply_markup=build_episode_keyboard(episodes, page=page)
        )
        await callback.answer()

    elif data.startswith("ep:"):
        ep_index = int(data.split(":")[1])
        ep       = episodes[ep_index]
        ts       = format_duration(ep["duration"])
        auto_fmt = detect_format(ep.get("url", ""))
        auto_label = "🎵 Audio" if auto_fmt == "mp3" else "🎬 Video"
        await callback.message.edit_text(
            f"{'🎵' if auto_fmt == 'mp3' else '🎬'} **{ep['title']}**\n"
            f"⏱ Duration: `{ts}`\n"
            f"🤖 Auto-detected: **{auto_label}**\n\n"
            f"Choose format:",
            reply_markup=build_format_keyboard(ep_index, ep)
        )
        await callback.answer()

    elif data.startswith("fmt:"):
        _, ep_index, fmt = data.split(":")
        ep_index = int(ep_index)
        ep       = episodes[ep_index]
        if fmt == "mp3":
            s = await get_settings(user_id)
            await callback.answer("⬇️ Added to queue...")
            await enqueue_download(client, callback.message, ep, fmt, s["quality"], user_id, meta)
        else:
            await callback.message.edit_text(
                f"🎬 **{ep['title']}**\n\nSelect quality:",
                reply_markup=build_quality_keyboard(ep_index, fmt)
            )
            await callback.answer()

    elif data.startswith("dl:"):
        parts    = data.split(":")
        ep_index = int(parts[1])
        fmt      = parts[2]
        quality  = parts[3]
        ep       = episodes[ep_index]
        await callback.answer("⬇️ Added to queue...")
        await enqueue_download(client, callback.message, ep, fmt, quality, user_id, meta)

    elif data.startswith("all:"):
        fmt       = data.split(":")[1]
        s         = await get_settings(user_id)
        quality   = s["quality"]
        fmt_label = "Auto 🤖" if fmt == "auto" else fmt.upper()
        await callback.answer(f"⬇️ Queuing all as {fmt_label}...")
        await callback.message.edit_text(
            f"📋 Queuing all {len(episodes)} episodes ({fmt_label} / {quality})..."
        )
        for ep in episodes:
            await enqueue_download(client, callback.message, ep, fmt, quality, user_id, meta, silent=True)
        # ✅ fix: use callback.message.chat.id instead of message.chat.id
        await client.send_message(
            callback.message.chat.id,
            f"✅ {len(episodes)} episodes added to queue. Use /queue to check."
        )

    elif data == "noop":
        await callback.answer()

    elif data == "cancel":
        event = cancel_events.get(user_id)
        if event:
            event.set()
            await callback.answer("🚫 Cancelling...", show_alert=False)
        else:
            await callback.answer("Nothing to cancel.", show_alert=False)

# ─────────────────────────────────────────
# MERGE CALLBACK HANDLER
# ─────────────────────────────────────────

async def handle_merge_callback(client, callback, user_id, data):
    session = await get_session(user_id)
    if not session:
        await callback.answer("❌ Session expired.", show_alert=True)
        return

    episodes = session["episodes"]
    selected = merge_selections.get(user_id, set())

    # ── Episode toggle ──────────────────────────────────────
    if data.startswith("msel:"):
        action = data.split(":")[1]
        if action == "all":
            merge_selections[user_id] = set(range(len(episodes)))
        elif action == "clear":
            merge_selections[user_id] = set()
        else:
            idx = int(action)
            if idx in selected:
                selected.discard(idx)
            else:
                selected.add(idx)
            merge_selections[user_id] = selected
        selected = merge_selections[user_id]
        await callback.message.edit_text(
            f"🔀 **Merge Mode** — {len(selected)} selected:",
            reply_markup=build_merge_select_keyboard(episodes, selected)
        )
        await callback.answer()

    # ── Merge page nav ──────────────────────────────────────
    elif data.startswith("mpage:"):
        page = int(data.split(":")[1])
        await callback.message.edit_text(
            f"🔀 **Merge Mode** — {len(selected)} selected:",
            reply_markup=build_merge_select_keyboard(episodes, selected, page=page)
        )
        await callback.answer()

    # ── Merge start (show selection UI) ────────────────────
    elif data == "merge:start":
        merge_selections[user_id] = set()
        await callback.message.edit_text(
            "🔀 **Merge Mode** — Select episodes to merge:",
            reply_markup=build_merge_select_keyboard(episodes, set(), page=0)
        )
        await callback.answer()

    # ── Show merge type selection ───────────────────────────
    elif data == "merge:type":
        count = len(selected)
        if count < 2:
            await callback.answer("Select at least 2 episodes!", show_alert=True)
            return
        await callback.message.edit_text(
            f"🔀 **Merge {count} episodes**\n\nChoose output type:",
            reply_markup=build_merge_type_keyboard(count)
        )
        await callback.answer()

    # ── Run merge ───────────────────────────────────────────
    elif data.startswith("merge:run:"):
        merge_type = data.split(":")[2]  # mp3 | mp4 | av
        indices    = sorted(selected)
        if len(indices) < 2:
            await callback.answer("Select at least 2 episodes!", show_alert=True)
            return
        selected_eps = [episodes[i] for i in indices]
        await callback.answer("🔀 Starting merge...")
        await callback.message.edit_text(
            f"⏳ Merging {len(indices)} episodes as **{merge_type.upper()}**..."
        )
        task = asyncio.create_task(
            run_merge(client, callback.message, selected_eps, merge_type, user_id, session["metadata"])
        )
        active_tasks[user_id] = task
        merge_selections.pop(user_id, None)

    # ── Cancel merge ────────────────────────────────────────
    elif data == "merge:cancel":
        merge_selections.pop(user_id, None)
        await callback.message.edit_text("❌ Merge cancelled.")
        await callback.answer()

# ─────────────────────────────────────────
# SCAN CALLBACK HANDLER
# ─────────────────────────────────────────

async def handle_scan_callback(client, callback, user_id, data):
    from database import get_session, get_settings
    from engine import enqueue_download
    from pyrogram.types import Message, Chat
    from utils import build_episode_keyboard
    
    if data.startswith("scan_pick:"):
        _, chat_id, msg_id = data.split(":")
        chat_id = int(chat_id) if chat_id.lstrip("-").isdigit() else chat_id
        msg_id = int(msg_id)
        
        await callback.message.edit_text("⏳ Fetching picked message...")
        try:
            msg = await client.get_messages(chat_id, msg_id)
            from plugins.commands import process_json_message
            await process_json_message(client, user_id, msg, callback.message)
        except Exception as e:
            await callback.message.edit_text(f"❌ Error fetching picked message: {e}")

    elif data == "scan:all":
        session = await get_session(user_id)
        if not session:
            await callback.answer("❌ Session expired. Scan again.", show_alert=True)
            return
        
        episodes = session["episodes"]
        meta = session["metadata"]
        s = await get_settings(user_id)
        fmt = s["format"]
        quality = s["quality"]
        
        await callback.answer(f"⬇️ Queuing all {len(episodes)} episodes...")
        
        # We might not be able to reply if we're in a channel and the user doesn't have post permissions, 
        # but we send the message to their DM anyway to confirm.
        try:
            await client.send_message(user_id, f"🚀 Queuing {len(episodes)} episodes for auto-download...")
        except Exception:
            pass
            
        dummy_msg = Message(id=0, chat=Chat(id=user_id, type="private"))
        
        for ep in episodes:
            await enqueue_download(client, dummy_msg, ep, fmt, quality, user_id, meta, silent=True)
            
        # Update the original message to remove the confirmation keyboard
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
            
    elif data == "scan:select":
        session = await get_session(user_id)
        if not session:
            await callback.answer("❌ Session expired. Scan again.", show_alert=True)
            return
        
        episodes = session["episodes"]
        await callback.message.edit_reply_markup(
            reply_markup=build_episode_keyboard(episodes, page=0)
        )
        await callback.answer()
        
    elif data == "scan:cancel":
        try:
            await callback.message.delete()
        except Exception:
            await callback.message.edit_text("❌ Scan cancelled.")
        await callback.answer("❌ Scan cancelled.")

# ─────────────────────────────────────────
# SETTINGS CALLBACK HANDLER
# ─────────────────────────────────────────


async def handle_settings_callback(client, callback, user_id, data):
    action = data.split(":")[1]
    s      = await get_settings(user_id)

    if action == "fmt_cycle":
        cur       = FMT_CYCLE.index(s["format"]) if s["format"] in FMT_CYCLE else 0
        s["format"] = FMT_CYCLE[(cur + 1) % len(FMT_CYCLE)]
        await save_settings(user_id, {"format": s["format"]})

    elif action == "qual_cycle":
        cur         = QUAL_CYCLE.index(s["quality"]) if s["quality"] in QUAL_CYCLE else 0
        s["quality"] = QUAL_CYCLE[(cur + 1) % len(QUAL_CYCLE)]
        await save_settings(user_id, {"quality": s["quality"]})

    elif action == "channel_toggle":
        s["channel_post"] = not s.get("channel_post", False)
        await save_settings(user_id, {"channel_post": s["channel_post"]})

    elif action == "filename_prompt":
        awaiting_filename.add(user_id)
        await callback.answer()
        await callback.message.reply_text(
            "📝 Send your filename template.\n\n"
            "Placeholders: `{title}` `{artist}` `{album}` `{n}`\n\n"
            "Example: `{n}. {title} - {artist}`"
        )
        return

    elif action == "done":
        await callback.answer("✅ Settings saved!")
        await callback.message.delete()
        return

    await callback.answer()
    await callback.message.edit_text(
        "⚙️ **Settings**\nTap to change:",
        reply_markup=build_settings_keyboard(s)
    )

@Client.on_message(filters.private & filters.text & ~filters.command(["start", "history", "cancel", "queue", "settings", "merge"]))
async def handle_text(client: Client, message: Message):
    if not message.from_user:
        return
    user_id = message.from_user.id
    if user_id in awaiting_filename:
        awaiting_filename.discard(user_id)
        template = message.text.strip()
        try:
            template.format(title="t", artist="a", album="b", n=1)
        except KeyError as e:
            await message.reply_text(f"❌ Invalid placeholder: {e}\nUse only: {{title}} {{artist}} {{album}} {{n}}")
            return
        await save_settings(user_id, {"filename_template": template})
        await message.reply_text(f"✅ Filename template saved: `{template}`")

