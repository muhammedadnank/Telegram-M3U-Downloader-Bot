# 📡 `/scan` Feature — Design Document

## Overview

User ഒരു Telegram channel message link അയക്കുന്നു → bot ആ message-ൽ നിന്ന് JSON file fetch ചെയ്യുന്നു → metadata + episodes parse → output channel-ൽ cover photo + details post → user confirm ചെയ്താൽ auto download queue start.

Single message link അല്ലെങ്കിൽ message range link support ചെയ്യുന്നു.

---

## 🔗 Supported Link Formats

```
# Single message — ഒരു specific message-ലെ JSON
/scan https://t.me/c/3994091348/2

# Range — message 2 മുതൽ 500 വരെ scan, JSON files കണ്ടെത്തുന്നു
/scan https://t.me/c/3994091348/2-500

# Format/quality override (both link types)
/scan https://t.me/c/3994091348/2        mp3
/scan https://t.me/c/3994091348/2-500    mp4  960p
```

---

## 🔁 Flow — Single Link

```
/scan https://t.me/c/3994091348/2
         ↓
chat_id = -1003994091348, message_id = 2
         ↓
client.get_messages(chat_id, message_id)
         ↓
message.document → .json file download
         ↓
JSON parse → metadata + episodes
         ↓
save_session(user_id, meta, episodes)
         ↓
Output channel: cover photo + details + confirm keyboard
         ↓
User taps ✅ Download All / 📋 Select Episodes / ❌ Cancel
```

---

## 🔁 Flow — Range Link

```
/scan https://t.me/c/3994091348/2-500
         ↓
chat_id = -1003994091348, start = 2, end = 500
         ↓
client.get_messages(chat_id, [2, 3, 4, ... 500])  ← batched (100 at a time)
         ↓
Filter messages with .document ending in .json
         ↓
Found JSON files list → show selection to user

  Case A: 1 JSON found → direct parse + post (same as single flow)
  Case B: Multiple JSON found → list them, user selects one
  Case C: 0 JSON found → "❌ No JSON files found in that range"
         ↓
Selected JSON → parse → save_session → output channel post
```

---

## 📥 Input Parsing — `parse_tg_link()`

```python
def parse_tg_link(link: str) -> dict:
    """
    Returns:
    {
        "chat_id": -1003994091348,   # int (private) or str (public username)
        "msg_start": 2,              # int
        "msg_end": 500,              # int or None (single message)
        "is_range": True/False
    }

    Examples:
    t.me/c/3994091348/2        → chat_id=-1003994091348, start=2, end=None
    t.me/c/3994091348/2-500   → chat_id=-1003994091348, start=2, end=500
    t.me/username/42           → chat_id="username", start=42, end=None
    t.me/username/10-200       → chat_id="username", start=10, end=200
    """
```

**Private channel chat_id conversion:**
```python
# t.me/c/3994091348/2  →  chat_id = -1003994091348
chat_id = int(f"-100{raw_id}")
```

---

## 📤 Output Channel Post Format

```
📀 Show Name

👤 Author: Artist Name
🌐 Language: Malayalam
📁 Type: Audiobook
🎞️ Episodes: 24
📅 Published: 2024-03-15
🔞 Age Rating: 13+

> Description line one
> Description line two...

[✅ Download All (24)]  [📋 Select Episodes]
[❌ Cancel]
```

- Cover art as photo (if `cover_url` available)
- Description quoted block (max 300 chars, truncated with `...`)
- Inline keyboard attached

---

## 📋 Multiple JSON Found UI (Range only)

When range scan finds multiple JSON files:

```
🔍 Found 3 JSON files in range 2–500:

1. The Silent Patient (Ep 1–20)   [msg #14]
2. Atomic Habits (Ep 1–30)        [msg #87]
3. Ikigai (Ep 1–15)               [msg #203]

Select one to download:
[1️⃣]  [2️⃣]  [3️⃣]  [❌ Cancel]
```

Callback data: `scan_pick:14`, `scan_pick:87`, `scan_pick:203`
→ bot fetches that specific message → normal single flow continues.

---

## 🧩 Components to Build

### 1. `parse_tg_link()` — `utils.py`
- Regex-based link parser
- Returns `chat_id`, `msg_start`, `msg_end`, `is_range`
- Handles private (`/c/`) and public (username) links

### 2. `build_scan_confirm_keyboard()` — `utils.py`
```python
InlineKeyboardMarkup([
    [
        InlineKeyboardButton(f"✅ Download All ({count})", callback_data="scan:all"),
        InlineKeyboardButton("📋 Select Episodes", callback_data="scan:select"),
    ],
    [InlineKeyboardButton("❌ Cancel", callback_data="scan:cancel")]
])
```

### 3. `build_scan_pick_keyboard()` — `utils.py` (range only)
```python
# One button per JSON file found
# callback_data = f"scan_pick:{message_id}"
```

### 4. `/scan` Command — `plugins/commands.py`
```
1. Parse args → link + optional fmt/quality
2. parse_tg_link(link)
3. if is_range → fetch_range() → filter JSONs
   else → fetch single message
4. Download JSON → parse
5. save_session()
6. Post to POST_CHANNEL (or DM if not configured)
```

### 5. Scan Callbacks — `plugins/callbacks.py`

| Callback | Action |
|---|---|
| `scan:all` | Queue all episodes (existing `enqueue_download` loop) |
| `scan:select` | Open existing merge select UI |
| `scan:cancel` | Delete message, clear session |
| `scan_pick:{msg_id}` | Fetch that message → parse JSON → continue single flow |

### 6. Range Fetcher — `plugins/commands.py`
```python
async def fetch_json_in_range(client, chat_id, start, end) -> list[Message]:
    """
    Fetches messages start→end in batches of 100.
    Returns list of messages that have a .json document.
    """
    json_messages = []
    ids = list(range(start, end + 1))
    for i in range(0, len(ids), 100):          # Pyrogram batch limit = 200
        batch = ids[i:i+100]
        msgs = await client.get_messages(chat_id, batch)
        for m in msgs:
            if m.document and m.document.file_name.endswith(".json"):
                json_messages.append(m)
    return json_messages
```

---

## ⚠️ Edge Cases & Handling

| Case | Handling |
|---|---|
| Bot not member of source channel | `UserNotParticipant` catch → "❌ Bot needs to be added to that channel first" |
| Single message has no JSON | "❌ No JSON document found in that message" |
| Range finds 0 JSON files | "❌ No JSON files found in messages {start}–{end}" |
| Range finds 1 JSON | Auto-select, skip pick UI, go direct to confirm |
| Range too large (>500 messages) | Cap at 500, warn user: "⚠️ Scanning first 500 messages only" |
| JSON parse fails | "❌ Could not parse JSON. Is it a valid show export?" |
| No `POST_CHANNEL` configured | Send confirm keyboard to user in DM instead |
| Duplicate scan (show already queued) | "⚠️ This show is already in your queue" |
| Invalid link format | "❌ Invalid Telegram link. Use format: t.me/c/ID/MSG or t.me/c/ID/START-END" |
| `msg_end < msg_start` | "❌ Invalid range: end must be greater than start" |

---

## 🗂️ Files to Modify

| File | Change |
|---|---|
| `src/utils.py` | Add `parse_tg_link()`, `build_scan_confirm_keyboard()`, `build_scan_pick_keyboard()` |
| `src/plugins/commands.py` | Add `/scan` handler + `fetch_json_in_range()` |
| `src/plugins/callbacks.py` | Add `scan:*` and `scan_pick:*` callback handlers |
| `src/config.py` | No change (`POST_CHANNEL` already exists) |
| `src/engine.py` | No change (existing queue reused) |
| `src/database.py` | No change (`save_session` reused) |

---

## 🔒 Permissions Required

- Bot must be **member** of source channel (private channels)
- Bot must have **post messages** permission in `POST_CHANNEL`
- No admin rights needed for source channel (read-only sufficient)

---

## 🧪 Test Cases

```
/scan https://t.me/c/3994091348/2              → single valid JSON
/scan https://t.me/c/3994091348/2 mp3          → single, force mp3
/scan https://t.me/c/3994091348/2-500          → range, multiple JSON
/scan https://t.me/c/3994091348/2-500 mp4 960p → range, force mp4 960p
/scan https://t.me/c/3994091348/5              → message has no JSON
/scan https://t.me/c/3994091348/500-2          → invalid range
/scan https://t.me/c/9999999999/1              → bot not in channel
/scan notavalidlink                             → invalid link
/scan https://t.me/somechannel/10-100          → public channel range
```

---

## 📦 Dependencies

No new packages needed. Uses existing:
- `pyrogram` — `get_messages()`, `download_media()`
- `motor` — `save_session()`
- `tempfile` — JSON download
- `json` — parse
- `re` — link parsing

---

## 🚀 Implementation Order

1. `parse_tg_link()` in `utils.py`
2. `build_scan_confirm_keyboard()` + `build_scan_pick_keyboard()` in `utils.py`
3. `fetch_json_in_range()` helper in `commands.py`
4. `/scan` command handler in `commands.py`
5. `scan:*` + `scan_pick:*` callbacks in `callbacks.py`
6. Test single link
7. Test range link (1 JSON, multiple JSON, 0 JSON)
8. Test with/without `POST_CHANNEL`