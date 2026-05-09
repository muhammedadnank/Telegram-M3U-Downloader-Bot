import re
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import QUALITY_OPTIONS

# ─────────────────────────────────────────
# M3U PARSER
# ─────────────────────────────────────────

def parse_m3u(content: str) -> dict:
    lines    = content.strip().splitlines()
    metadata = {}
    episodes = []

    for line in lines:
        line = line.strip()
        if line.startswith("#EXTART:"):
            metadata["artist"] = line[8:]
        elif line.startswith("#EXTALB:"):
            metadata["album"] = line[8:]
        elif line.startswith("#PLAYLIST:"):
            metadata["playlist"] = line[10:]
        elif line.startswith("#EXTINF:"):
            match = re.match(r"#EXTINF:(-?\d+)[^,]*,(.*)", line)
            if match:
                episodes.append({
                    "duration": max(0, int(match.group(1))),
                    "title":    match.group(2).strip(),
                    "url":      None
                })
        elif line and not line.startswith("#"):
            if episodes and episodes[-1]["url"] is None:
                episodes[-1]["url"] = line

    episodes = [ep for ep in episodes if ep.get("url")]
    return {"metadata": metadata, "episodes": episodes}

# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────

def format_duration(seconds: int) -> str:
    seconds = max(0, seconds)
    h, rem  = divmod(seconds, 3600)
    m, s    = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

def detect_format(url: str) -> str:
    url_lower   = url.lower()
    audio_exts  = (".mp3", ".aac", ".flac", ".ogg", ".opus", ".wav", ".m4a")
    audio_hosts = ("soundcloud.com", "spotify.com", "music.youtube.com",
                   "audiomack.com", "bandcamp.com", "podcast", "audio")
    if any(url_lower.endswith(ext) for ext in audio_exts):
        return "mp3"
    if any(host in url_lower for host in audio_hosts):
        return "mp3"
    return "mp4"

def build_filename(template: str, title: str, artist: str, album: str, n: int) -> str:
    name = template.format(title=title, artist=artist or "Unknown", album=album or "Unknown", n=n)
    return re.sub(r'[\\/*?:"<>|]', "_", name)

# ─────────────────────────────────────────
# KEYBOARDS
# ─────────────────────────────────────────

def build_episode_keyboard(episodes: list, page: int = 0) -> InlineKeyboardMarkup:
    per_page    = 10
    start       = page * per_page
    end         = min(start + per_page, len(episodes))
    total_pages = (len(episodes) + per_page - 1) // per_page

    buttons = []
    for i in range(start, end):
        ep        = episodes[i]
        ts        = format_duration(ep["duration"])
        auto_fmt  = detect_format(ep.get("url", ""))
        fmt_badge = "🎵" if auto_fmt == "mp3" else "🎬"
        buttons.append([InlineKeyboardButton(
            f"{fmt_badge} {ep['title']}  [{ts}]",
            callback_data=f"ep:{i}"
        )])

    buttons.append([
        InlineKeyboardButton("⬇️ All (Auto)", callback_data="all:auto"),
        InlineKeyboardButton("⬇️ All MP3",    callback_data="all:mp3"),
        InlineKeyboardButton("⬇️ All MP4",    callback_data="all:mp4"),
    ])
    buttons.append([
        InlineKeyboardButton("🔀 Merge Episodes", callback_data="merge:start"),
    ])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"page:{page-1}"))
    nav.append(InlineKeyboardButton(f"📄 {page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"page:{page+1}"))
    buttons.append(nav)

    return InlineKeyboardMarkup(buttons)

def build_format_keyboard(ep_index: int, episode: dict) -> InlineKeyboardMarkup:
    ts        = format_duration(episode["duration"])
    auto_fmt  = detect_format(episode.get("url", ""))
    auto_label = f"{'🎵 MP3' if auto_fmt == 'mp3' else '🎬 MP4'} (Auto ✨)"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(auto_label,    callback_data=f"fmt:{ep_index}:{auto_fmt}")],
        [
            InlineKeyboardButton("🎵 MP3",   callback_data=f"fmt:{ep_index}:mp3"),
            InlineKeyboardButton("🎬 MP4",   callback_data=f"fmt:{ep_index}:mp4"),
        ],
        [InlineKeyboardButton(f"⏱ {ts}  •  🔙 Back", callback_data="back:0")]
    ])

def build_quality_keyboard(ep_index: int, fmt: str) -> InlineKeyboardMarkup:
    buttons = []
    for key, (label, _) in QUALITY_OPTIONS.items():
        buttons.append([InlineKeyboardButton(
            f"{'✨ ' if key == 'best' else ''}{label}",
            callback_data=f"dl:{ep_index}:{fmt}:{key}"
        )])
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data=f"ep:{ep_index}")])
    return InlineKeyboardMarkup(buttons)

def build_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🚫 Cancel", callback_data="cancel")]])

def build_settings_keyboard(s: dict) -> InlineKeyboardMarkup:
    fmt_labels  = {"auto": "Auto 🤖", "mp3": "MP3 🎵", "mp4": "MP4 🎬"}
    qual_labels = {k: v[0] for k, v in QUALITY_OPTIONS.items()}
    ch_label    = "✅ On" if s.get("channel_post") else "❌ Off"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Format: {fmt_labels.get(s['format'], s['format'])}", callback_data="set:fmt_cycle")],
        [InlineKeyboardButton(f"Quality: {qual_labels.get(s['quality'], s['quality'])}", callback_data="set:qual_cycle")],
        [InlineKeyboardButton(f"Auto-post to channel: {ch_label}", callback_data="set:channel_toggle")],
        [InlineKeyboardButton(f"📝 Filename: {s['filename_template']}", callback_data="set:filename_prompt")],
        [InlineKeyboardButton("✅ Done", callback_data="set:done")],
    ])

# ── Merge keyboards ───────────────────────────────────────

def build_merge_select_keyboard(episodes: list, selected: set, page: int = 0) -> InlineKeyboardMarkup:
    """Episode multi-select for merge."""
    per_page    = 8
    start       = page * per_page
    end         = min(start + per_page, len(episodes))
    total_pages = (len(episodes) + per_page - 1) // per_page

    buttons = []
    for i in range(start, end):
        ep      = episodes[i]
        checked = "✅" if i in selected else "⬜"
        buttons.append([InlineKeyboardButton(
            f"{checked} {ep['title']}",
            callback_data=f"msel:{i}"
        )])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"mpage:{page-1}"))
    nav.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"mpage:{page+1}"))
    if nav:
        buttons.append(nav)

    count = len(selected)
    buttons.append([
        InlineKeyboardButton(f"Select All ({len(episodes)})", callback_data="msel:all"),
        InlineKeyboardButton("Clear", callback_data="msel:clear"),
    ])
    if count >= 2:
        buttons.append([InlineKeyboardButton(f"▶️ Merge {count} episodes →", callback_data="merge:type")])
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="merge:cancel")])
    return InlineKeyboardMarkup(buttons)

def build_merge_type_keyboard(count: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🎵 Merge as MP3 ({count} eps)", callback_data="merge:run:mp3")],
        [InlineKeyboardButton(f"🎬 Merge as MP4 ({count} eps)", callback_data="merge:run:mp4")],
        [InlineKeyboardButton(f"🎬+🎵 Merge Video + External Audio", callback_data="merge:run:av")],
        [InlineKeyboardButton("🔙 Back", callback_data="merge:start")],
    ])

# ── Scan feature helpers ─────────────────────────────────

def parse_tg_link(link: str) -> dict:
    match = re.match(r"https?://t\.me/(?:c/(\d+)/|([\w_]+)/)(\d+)(?:-(\d+))?", link)
    if not match:
        return {}
    
    chat_id_str, username, start_str, end_str = match.groups()
    start = int(start_str)
    
    if chat_id_str:
        chat_id = int(f"-100{chat_id_str}")
    else:
        chat_id = username
        
    return {
        "chat_id": chat_id,
        "msg_start": start,
        "msg_end": int(end_str) if end_str else None,
        "is_range": bool(end_str)
    }

def build_scan_confirm_keyboard(count: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"✅ Download All ({count})", callback_data="scan:all"),
            InlineKeyboardButton("📋 Select Episodes", callback_data="scan:select"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="scan:cancel")]
    ])

def build_scan_pick_keyboard(json_messages: list) -> InlineKeyboardMarkup:
    buttons = []
    row = []
    
    emoji_nums = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    
    for i, m in enumerate(json_messages):
        label = emoji_nums[i] if i < len(emoji_nums) else f"[{i+1}]"
        # store chat_id and message_id
        row.append(InlineKeyboardButton(label, callback_data=f"scan_pick:{m.chat.id}:{m.id}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
            
    if row:
        buttons.append(row)
        
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="scan:cancel")])
    return InlineKeyboardMarkup(buttons)

def parse_json_data(data: dict) -> tuple[dict, list]:
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
    return meta, episodes

def build_caption(meta: dict, episodes: list) -> str:
    playlist_name = meta.get("playlist", meta.get("album", "Playlist"))
    artist        = meta.get("artist", "Unknown")
    
    caption = f"**{playlist_name}**\n\n"
    if artist and artist != "Unknown":
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
        
    return caption

