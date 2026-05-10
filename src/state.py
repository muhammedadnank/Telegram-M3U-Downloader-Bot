import asyncio
from collections import deque
from config import QUALITY_OPTIONS

# ─────────────────────────────────────────
# RUNTIME STATE
# ─────────────────────────────────────────

cancel_events: dict[int, asyncio.Event] = {}
active_tasks:  dict[int, asyncio.Task]  = {}
queue_items:   dict[int, deque]         = {}

CONCURRENT_LIMIT   = 3
download_semaphore = asyncio.Semaphore(CONCURRENT_LIMIT)

# Merge selection state: user_id -> set of episode indices
merge_selections: dict[int, set] = {}
merge_mode:       dict[int, str] = {}  # user_id -> "mp3" | "mp4" | "av"


FMT_CYCLE  = ["auto", "mp3", "mp4"]
QUAL_CYCLE = list(QUALITY_OPTIONS.keys())
awaiting_filename: set[int] = set()

awaiting_merge_range: set[int] = set()
