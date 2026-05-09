import os
import re
from collections import deque
import json as _json
import asyncio
import tempfile
import time
import urllib.request
from pathlib import Path
from pyrogram import Client
from pyrogram.types import Message

from config import QUALITY_OPTIONS, POST_CHANNEL
from state import queue_items, active_tasks, download_semaphore, cancel_events
from database import get_settings, log_download
from utils import detect_format, build_filename, build_cancel_keyboard

# ─────────────────────────────────────────
# QUEUE & DOWNLOAD ENGINE
# ─────────────────────────────────────────

async def enqueue_download(
    client, message, episode, fmt, quality, user_id, meta,
    batch_index=None, total=None, silent=False
):
    if user_id not in queue_items:
        queue_items[user_id] = deque()

    job = {
        "episode": episode, "fmt": fmt, "quality": quality,
        "meta": meta, "message": message,
        "batch_index": batch_index, "total": total,
    }
    queue_items[user_id].append(job)

    if not silent:
        pos = len(queue_items[user_id])
        if pos > 1:
            await client.send_message(
                message.chat.id,
                f"📋 **{episode['title']}** added to queue (position {pos})"
            )

    if user_id not in active_tasks or active_tasks[user_id].done():
        task = asyncio.create_task(process_queue(client, user_id))
        active_tasks[user_id] = task

async def process_queue(client, user_id):
    while True:
        q = queue_items.get(user_id)
        if not q:
            break
        job = q[0]
        try:
            async with download_semaphore:
                await download_and_send(
                    client=client, message=job["message"],
                    episode=job["episode"], fmt=job["fmt"],
                    quality=job["quality"], user_id=user_id,
                    meta=job["meta"], batch_index=job.get("batch_index"),
                    total=job.get("total"),
                )
        except Exception:
            pass
        finally:
            q.popleft()

# ─────────────────────────────────────────
# DOWNLOAD & SEND
# ─────────────────────────────────────────

async def download_and_send(
    client: Client, message: Message,
    episode: dict, fmt: str, quality: str,
    user_id: int, meta: dict,
    batch_index: int = None, total: int = None,
):
    title = episode["title"]
    url   = episode.get("url")

    if fmt == "auto":
        fmt = detect_format(url or "")

    if not url or not url.startswith(("http://", "https://")):
        await client.send_message(message.chat.id, f"❌ Invalid URL for **{title}**")
        await log_download(user_id, episode, fmt, quality, success=False)
        return

    cancel_event = asyncio.Event()
    cancel_events[user_id] = cancel_event

    prefix     = f"[{batch_index}/{total}] " if batch_index else ""
    status_msg = await client.send_message(
        chat_id=message.chat.id,
        text=f"⏳ {prefix}Downloading **{title}**...\n📊 Quality: `{quality}`",
        reply_markup=build_cancel_keyboard()
    )
    dl_start = time.monotonic()

    s             = await get_settings(user_id)
    filename_base = build_filename(
        template=s.get("filename_template", "{title}"),
        title=title, artist=meta.get("artist", ""),
        album=meta.get("album", meta.get("playlist", "")),
        n=batch_index or 1,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, f"{filename_base}.%(ext)s")

        if fmt == "mp3":
            cmd = [
                "yt-dlp", "-x", "--audio-format", "mp3",
                "--audio-quality", "0", "--embed-thumbnail",
                "--add-metadata", "--newline",
                "--concurrent-fragments", "5",
                "-o", out_path, "--no-playlist", "--continue", url
            ]
        else:
            _, format_selector = QUALITY_OPTIONS.get(quality, QUALITY_OPTIONS["best"])
            cmd = [
                "yt-dlp", "-f", format_selector,
                "--merge-output-format", "mp4", "--newline",
                "--concurrent-fragments", "5",
                "-o", out_path, "--no-playlist", "--continue", url
            ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

            dl_progress_pattern = (
                r"\[download\]\s+([\d.]+)%\s+of\s+([~]*[\d.]+\s*\S+)"
                r"(?:.*at\s+([\d.]+\s*\S+/s))?(?:.*ETA\s+([\d:]+))?"
            )
            stderr_lines = []
            last_edit    = [0.0]
            dl_pct       = [0.0]
            dl_speed     = ["--"]
            dl_eta       = ["--"]
            dl_size      = ["--"]

            async def read_stdout():
                async for raw_line in proc.stdout:
                    line = raw_line.decode(errors="ignore").strip()
                    stderr_lines.append(line)
                    m = re.search(dl_progress_pattern, line)
                    if m:
                        dl_pct[0]   = float(m.group(1))
                        dl_size[0]  = m.group(2).strip()
                        dl_speed[0] = m.group(3).strip() if m.group(3) else "--"
                        dl_eta[0]   = m.group(4) if m.group(4) else "--"
                        now = time.monotonic()
                        if now - last_edit[0] < 3 or cancel_event.is_set():
                            continue
                        last_edit[0] = now
                        bar = "█" * int(dl_pct[0] / 10) + "░" * (10 - int(dl_pct[0] / 10))
                        try:
                            await status_msg.edit_text(
                                f"⬇️ {prefix}**{title}**\n"
                                f"`[{bar}]` {dl_pct[0]:.1f}%\n"
                                f"📦 {dl_size[0]}  •  ⚡ {dl_speed[0]}\n"
                                f"⏳ ETA: {dl_eta[0]}  •  ⏱ {time.monotonic()-dl_start:.0f}s elapsed\n"
                                f"📊 {fmt.upper()} • {quality}",
                                reply_markup=build_cancel_keyboard()
                            )
                        except Exception:
                            pass

            read_task   = asyncio.create_task(read_stdout())
            cancel_task = asyncio.create_task(cancel_event.wait())

            try:
                await asyncio.wait_for(asyncio.shield(read_task), timeout=600)
            except asyncio.TimeoutError:
                proc.kill()
                await read_task
                await status_msg.edit_text(f"❌ Timed out: **{title}**", reply_markup=None)
                await log_download(user_id, episode, fmt, quality, success=False)
                cancel_events.pop(user_id, None)
                return

            cancel_task.cancel()
            await proc.wait()
            dl_elapsed = time.monotonic() - dl_start

            if cancel_event.is_set():
                proc.kill()
                await status_msg.edit_text(f"🚫 Cancelled: **{title}**", reply_markup=None)
                await log_download(user_id, episode, fmt, quality, success=False)
                cancel_events.pop(user_id, None)
                return

            if proc.returncode != 0:
                error_text = "\n".join(stderr_lines[-10:])
                if "Private video" in error_text:       reason = "Video is private"
                elif "geo" in error_text.lower():        reason = "Geo-restricted"
                elif "not available" in error_text.lower(): reason = "Not available"
                elif "unable to download" in error_text.lower(): reason = "Unable to download"
                else:                                    reason = "Download failed"
                await status_msg.edit_text(
                    f"❌ {reason}: **{title}**\n`{error_text[-300:]}`", reply_markup=None
                )
                await log_download(user_id, episode, fmt, quality, success=False)
                cancel_events.pop(user_id, None)
                return

            ext   = "mp3" if fmt == "mp3" else "mp4"
            files = list(Path(tmpdir).glob(f"*.{ext}")) or list(Path(tmpdir).glob("*.*"))
            if not files:
                await status_msg.edit_text(f"❌ File missing: **{title}**", reply_markup=None)
                await log_download(user_id, episode, fmt, quality, success=False)
                cancel_events.pop(user_id, None)
                return

            file_path    = str(files[0])
            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)

            if file_size_mb > 2000:
                await status_msg.edit_text(
                    f"❌ **{title}** too large ({file_size_mb:.1f} MB).", reply_markup=None
                )
                await log_download(user_id, episode, fmt, quality, success=False)
                cancel_events.pop(user_id, None)
                return

            # ffprobe — video duration + dimensions
            vid_duration = episode.get("duration", 0)
            vid_width = vid_height = 0
            if fmt != "mp3":
                try:
                    probe = await asyncio.create_subprocess_exec(
                        "ffprobe", "-v", "quiet", "-print_format", "json",
                        "-show_streams", "-show_format", file_path,
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                    )
                    probe_out, _ = await probe.communicate()
                    probe_data   = _json.loads(probe_out.decode())
                    if probe_data.get("format", {}).get("duration"):
                        vid_duration = int(float(probe_data["format"]["duration"]))
                    for stream in probe_data.get("streams", []):
                        if stream.get("codec_type") == "video":
                            vid_width  = stream.get("width", 0)
                            vid_height = stream.get("height", 0)
                            break
                except Exception:
                    pass

            # Thumbnail and Metadata Tagging
            thumb_path = None
            if meta.get("cover_url"):
                thumb_file = os.path.join(tmpdir, "cover.jpg")
                try:
                    # Download cover using ffmpeg to convert webp to jpg safely
                    tp = await asyncio.create_subprocess_exec(
                        "ffmpeg", "-y", "-i", meta["cover_url"], "-vframes", "1", thumb_file,
                        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
                    )
                    await tp.wait()
                    if os.path.exists(thumb_file) and os.path.getsize(thumb_file) > 0:
                        thumb_path = thumb_file
                except Exception:
                    pass

            # If no cover downloaded, try extracting from video (if mp4)
            if fmt != "mp3" and not thumb_path:
                try:
                    thumb_file = os.path.join(tmpdir, "thumb.jpg")
                    tp = await asyncio.create_subprocess_exec(
                        "ffmpeg", "-y", "-ss", "10", "-i", file_path,
                        "-vframes", "1", "-vf", "scale=320:-1", thumb_file,
                        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
                    )
                    await tp.wait()
                    if os.path.exists(thumb_file) and os.path.getsize(thumb_file) > 0:
                        thumb_path = thumb_file
                except Exception:
                    pass

            # Apply Metadata using FFmpeg
            playlist_name = meta.get("playlist", meta.get("album", "Audio"))
            artist = meta.get("artist", "")
            has_metadata = bool(thumb_path or artist or meta.get("playlist") or meta.get("album"))

            ep_index = episode.get("index", "")
            index_prefix = f"{ep_index} ⛥ " if ep_index != "" else ""
            if has_metadata:
                final_name = f"{index_prefix}{playlist_name} ⛥ @PFMXBOT.{ext}"
                final_name = re.sub(r'[\\/*?:"<>|]', "", final_name)
                tagged_file = os.path.join(tmpdir, final_name)
                
                ffmpeg_meta_cmd = [
                    "ffmpeg", "-y", "-i", file_path
                ]
                if thumb_path:
                    ffmpeg_meta_cmd.extend(["-i", thumb_path])
                
                ffmpeg_meta_cmd.extend([
                    "-map", "0",
                ])
                if thumb_path:
                    if fmt == "mp3":
                        ffmpeg_meta_cmd.extend(["-map", "1:0", "-id3v2_version", "3", "-metadata:s:v", "title=Album cover", "-metadata:s:v", "comment=Cover (front)"])
                    else:
                        ffmpeg_meta_cmd.extend(["-map", "1", "-disposition:v:1", "attached_pic"])

                artist_tag = f"{artist} ⛥ @PFMXBOT" if artist else "@PFMXBOT"
                ffmpeg_meta_cmd.extend([
                    "-c", "copy",
                    "-metadata", f"title={index_prefix}{playlist_name}",
                    "-metadata", f"artist={artist_tag}",
                    "-metadata", f"author={artist_tag}",
                    "-metadata", f"album={playlist_name}",
                    tagged_file
                ])

                try:
                    tag_proc = await asyncio.create_subprocess_exec(
                        *ffmpeg_meta_cmd,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL
                    )
                    await tag_proc.wait()
                    if os.path.exists(tagged_file) and os.path.getsize(tagged_file) > 0:
                        file_path = tagged_file
                except Exception:
                    pass

            # Phase switch
            await status_msg.edit_text(
                f"✅ Downloaded **{title}**\n`[██████████]` 100%\n"
                f"📦 {dl_size[0]}  •  ⏱ {dl_elapsed:.0f}s\n📤 Preparing upload...",
                reply_markup=build_cancel_keyboard()
            )

            upload_start = time.monotonic()
            _last_edit   = [0.0]

            async def upload_progress(current, total_bytes):
                if cancel_event.is_set():
                    return
                now = time.monotonic()
                if now - _last_edit[0] < 3:
                    return
                _last_edit[0] = now
                elapsed   = now - upload_start
                pct       = (current / total_bytes * 100) if total_bytes else 0
                speed_b   = current / elapsed if elapsed > 0 else 0
                speed_str = f"{speed_b/(1024*1024):.1f} MB/s" if speed_b >= 1024*1024 else f"{speed_b/1024:.0f} KB/s"
                eta_s     = int((total_bytes - current) / speed_b) if speed_b > 0 else 0
                eta_str   = f"{eta_s//60}m {eta_s%60}s" if eta_s >= 60 else f"{eta_s}s"
                bar       = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
                try:
                    await status_msg.edit_text(
                        f"📤 {prefix}**{title}**\n`[{bar}]` {pct:.1f}%\n"
                        f"📦 {current/(1024*1024):.1f} / {file_size_mb:.1f} MB  •  ⚡ {speed_str}\n"
                        f"⏳ ETA: {eta_str}  •  ⬇️ took {dl_elapsed:.0f}s",
                        reply_markup=build_cancel_keyboard()
                    )
                except Exception:
                    pass

            caption  = f"**{title}**"
            caption += f"\n📀 {meta['playlist']}" if meta.get("playlist") else ""
            caption += f"\n👤 {meta['artist']}"   if meta.get("artist")   else ""
            caption += f"\n📊 {fmt.upper()} • {quality}"

            send_kwargs = dict(chat_id=message.chat.id, caption=caption, progress=upload_progress)

            if fmt == "mp3":
                performer_str = f"{meta.get('artist', 'Unknown')} ⛥ @PFMXBOT"
                tg_title = f"{index_prefix}{playlist_name}" if has_metadata else title
                sent = await client.send_audio(
                    audio=file_path, title=tg_title,
                    performer=performer_str,
                    duration=vid_duration,
                    thumb=thumb_path,
                    **send_kwargs
                )
            else:
                sent = await client.send_video(
                    video=file_path, supports_streaming=True,
                    thumb=thumb_path, duration=vid_duration,
                    width=vid_width or None, height=vid_height or None,
                    **send_kwargs
                )

            upload_elapsed = time.monotonic() - upload_start
            total_elapsed  = time.monotonic() - dl_start

            await log_download(user_id, episode, fmt, quality, success=True)
            await status_msg.edit_text(
                f"✅ **{title}**\n"
                f"📦 {file_size_mb:.1f} MB  •  ⬇️ {dl_elapsed:.0f}s  •  📤 {upload_elapsed:.0f}s\n"
                f"⏱ Total: {total_elapsed:.0f}s",
                reply_markup=None
            )

            if s.get("channel_post") and POST_CHANNEL:
                try:
                    await sent.copy(POST_CHANNEL)
                except Exception as e:
                    await client.send_message(message.chat.id, f"⚠️ Channel post failed: `{e}`")

        except Exception as e:
            await status_msg.edit_text(f"❌ Error: `{str(e)}`", reply_markup=None)
            await log_download(user_id, episode, fmt, quality, success=False)
        finally:
            cancel_events.pop(user_id, None)

# ─────────────────────────────────────────
# MERGE ENGINE
# ─────────────────────────────────────────

async def run_merge(
    client: Client, message: Message,
    episodes: list, merge_type: str,
    user_id: int, meta: dict,
):
    """
    merge_type:
      mp3 — download all as audio → concat → single MP3 with chapters
      mp4 — download all as video → concat → single MP4 with chapters
      av  — download video stream + separate audio → mux into MP4
    """
    chat_id    = message.chat.id
    total      = len(episodes)
    status_msg = await client.send_message(
        chat_id,
        f"🔀 Merging {total} episodes as **{merge_type.upper()}**\n"
        f"⏳ Step 1/{total+2}: Downloading...",
        reply_markup=build_cancel_keyboard()
    )

    cancel_event = asyncio.Event()
    cancel_events[user_id] = cancel_event

    with tempfile.TemporaryDirectory() as tmpdir:
        downloaded_files = []

        # ── Step 1: Download all episodes ──────────────────────
        for i, ep in enumerate(episodes, 1):
            if cancel_event.is_set():
                await status_msg.edit_text("🚫 Merge cancelled.", reply_markup=None)
                cancel_events.pop(user_id, None)
                return

            url   = ep.get("url", "")
            title = ep["title"]
            safe  = re.sub(r'[\\/*?:"<>|]', "_", title)
            out   = os.path.join(tmpdir, f"{i:03d}_{safe}.%(ext)s")

            await status_msg.edit_text(
                f"🔀 Merging {total} episodes\n"
                f"⬇️ [{i}/{total}] Downloading: **{title}**",
                reply_markup=build_cancel_keyboard()
            )

            if merge_type == "mp3":
                cmd = [
                    "yt-dlp", "-x", "--audio-format", "mp3",
                    "--audio-quality", "0", "--newline",
                    "-o", out, "--no-playlist", "--continue", url
                ]
            elif merge_type == "av":
                # Download video-only + audio-only separately
                vid_out = os.path.join(tmpdir, f"{i:03d}_{safe}_video.%(ext)s")
                aud_out = os.path.join(tmpdir, f"{i:03d}_{safe}_audio.%(ext)s")
                # Video stream
                cmd = [
                    "yt-dlp", "-f", "bestvideo",
                    "-o", vid_out, "--no-playlist", "--continue", url
                ]
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL
                )
                await proc.wait()
                # Audio stream
                cmd2 = [
                    "yt-dlp", "-f", "bestaudio",
                    "-o", aud_out, "--no-playlist", "--continue", url
                ]
                proc2 = await asyncio.create_subprocess_exec(
                    *cmd2,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL
                )
                await proc2.wait()
                # Mux video + audio
                vid_files = sorted(Path(tmpdir).glob(f"{i:03d}_{safe}_video.*"))
                aud_files = sorted(Path(tmpdir).glob(f"{i:03d}_{safe}_audio.*"))
                if vid_files and aud_files:
                    muxed = os.path.join(tmpdir, f"{i:03d}_{safe}_muxed.mp4")
                    mux = await asyncio.create_subprocess_exec(
                        "ffmpeg", "-y",
                        "-i", str(vid_files[0]),
                        "-i", str(aud_files[0]),
                        "-c:v", "copy", "-c:a", "aac",
                        muxed,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL
                    )
                    await mux.wait()
                    downloaded_files.append((title, muxed))
                continue
            else:  # mp4
                cmd = [
                    "yt-dlp", "-f", "bestvideo+bestaudio/best",
                    "--merge-output-format", "mp4", "--newline",
                    "-o", out, "--no-playlist", "--continue", url
                ]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await proc.wait()

            ext      = "mp3" if merge_type == "mp3" else "mp4"
            ep_files = sorted(Path(tmpdir).glob(f"{i:03d}_{safe}*.{ext}"))
            if ep_files:
                downloaded_files.append((title, str(ep_files[0])))

        if not downloaded_files:
            await status_msg.edit_text("❌ No files downloaded for merge.", reply_markup=None)
            cancel_events.pop(user_id, None)
            return

        if cancel_event.is_set():
            await status_msg.edit_text("🚫 Merge cancelled.", reply_markup=None)
            cancel_events.pop(user_id, None)
            return

        # ── Step 2: Concat with chapter markers ────────────────
        await status_msg.edit_text(
            f"🔀 Downloaded {len(downloaded_files)}/{total} files\n⚙️ Merging with chapters...",
            reply_markup=build_cancel_keyboard()
        )

        ext         = "mp3" if merge_type == "mp3" else "mp4"
        output_file = os.path.join(tmpdir, f"merged_output.{ext}")
        concat_list = os.path.join(tmpdir, "concat.txt")

        with open(concat_list, "w") as f:
            for _, fpath in downloaded_files:
                f.write(f"file '{fpath}'\n")

        # Build ffmpeg metadata with chapter marks
        metadata_file = os.path.join(tmpdir, "chapters.txt")
        chapters_meta = ";FFMETADATA1\n"
        cursor_ms     = 0

        for title, fpath in downloaded_files:
            # Get duration via ffprobe
            dur_ms = 0
            try:
                probe = await asyncio.create_subprocess_exec(
                    "ffprobe", "-v", "quiet", "-print_format", "json",
                    "-show_format", fpath,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
                )
                probe_out, _ = await probe.communicate()
                dur_s  = float(_json.loads(probe_out.decode()).get("format", {}).get("duration", 0))
                dur_ms = int(dur_s * 1000)
            except Exception:
                pass

            chapters_meta += (
                f"\n[CHAPTER]\nTIMEBASE=1/1000\n"
                f"START={cursor_ms}\nEND={cursor_ms + dur_ms}\n"
                f"title={title}\n"
            )
            cursor_ms += dur_ms

        with open(metadata_file, "w", encoding="utf-8") as f:
            f.write(chapters_meta)

        # ffmpeg concat — copy streams (fast, no re-encode)
        playlist_name = meta.get("playlist", meta.get("album", "Merged"))
        artist = meta.get("artist", "")
        
        # Download cover if available using ffmpeg to ensure it's a jpg
        cover_path = None
        if meta.get("cover_url"):
            cover_file = os.path.join(tmpdir, "cover.jpg")
            try:
                tp = await asyncio.create_subprocess_exec(
                    "ffmpeg", "-y", "-i", meta["cover_url"], "-vframes", "1", cover_file,
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
                )
                await tp.wait()
                if os.path.exists(cover_file) and os.path.getsize(cover_file) > 0:
                    cover_path = cover_file
            except Exception:
                pass

        safe_playlist = playlist_name if playlist_name else "Merged"
        # Build episode range label
        ep_nums = []
        for ep in episodes:
            t = ep.get("title", "")
            nums = re.findall(r'\d+', t)
            if nums:
                ep_nums.append(int(nums[-1]))
        if ep_nums:
            ep_range = f"Ep {min(ep_nums)} - {max(ep_nums)}" if len(set(ep_nums)) > 1 else f"Ep {ep_nums[0]}"
        else:
            ep_range = f"Ep 1 - {len(episodes)}"

        final_name = f"{ep_range} ⛥ {safe_playlist} ⛥ @PFMXBOT.{ext}"
        final_name = re.sub(r'[\\/*?:"<>|]', "", final_name)
        output_file = os.path.join(tmpdir, final_name)

        concat_cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", concat_list,
            "-i", metadata_file,
        ]
        
        if cover_path:
            concat_cmd.extend(["-i", cover_path])

        concat_cmd.extend([
            "-map_metadata", "1",
            "-map", "0",
        ])

        if cover_path:
            if merge_type == "mp3":
                concat_cmd.extend(["-map", "2:0", "-id3v2_version", "3", "-metadata:s:v", "title=Album cover", "-metadata:s:v", "comment=Cover (front)"])
            else:
                concat_cmd.extend(["-map", "2", "-disposition:v:1", "attached_pic"])

        artist_tag = f"{artist} ⛥ @PFMXBOT" if artist else "@PFMXBOT"
        tg_title = f"{ep_range} ⛥ {playlist_name}"
        concat_cmd.extend([
            "-c", "copy",
            "-metadata", f"title={tg_title}",
            "-metadata", f"artist={artist_tag}",
            "-metadata", f"author={artist_tag}",
            "-metadata", f"album={playlist_name}",
            output_file
        ])

        ffmpeg_proc = await asyncio.create_subprocess_exec(
            *concat_cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE
        )
        _, ffmpeg_err = await ffmpeg_proc.communicate()

        if ffmpeg_proc.returncode != 0:
            err = ffmpeg_err.decode()[-500:]
            await status_msg.edit_text(f"❌ Merge failed:\n`{err}`", reply_markup=None)
            cancel_events.pop(user_id, None)
            return

        if not os.path.exists(output_file):
            await status_msg.edit_text("❌ Merged file not found.", reply_markup=None)
            cancel_events.pop(user_id, None)
            return

        file_size_mb = os.path.getsize(output_file) / (1024 * 1024)

        if file_size_mb > 2000:
            await status_msg.edit_text(
                f"❌ Merged file too large ({file_size_mb:.1f} MB). Telegram limit is 2GB.",
                reply_markup=None
            )
            cancel_events.pop(user_id, None)
            return

        # ── Step 3: Upload ─────────────────────────────────────
        await status_msg.edit_text(
            f"📤 Uploading merged file ({file_size_mb:.1f} MB)...",
            reply_markup=build_cancel_keyboard()
        )

        upload_start = time.monotonic()
        _last_edit   = [0.0]

        async def merge_upload_progress(current, total_bytes):
            now = time.monotonic()
            if now - _last_edit[0] < 3:
                return
            _last_edit[0] = now
            elapsed   = now - upload_start
            pct       = (current / total_bytes * 100) if total_bytes else 0
            speed_b   = current / elapsed if elapsed > 0 else 0
            speed_str = f"{speed_b/(1024*1024):.1f} MB/s" if speed_b >= 1024*1024 else f"{speed_b/1024:.0f} KB/s"
            eta_s     = int((total_bytes - current) / speed_b) if speed_b > 0 else 0
            eta_str   = f"{eta_s//60}m {eta_s%60}s" if eta_s >= 60 else f"{eta_s}s"
            bar       = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
            try:
                await status_msg.edit_text(
                    f"📤 Uploading merged file\n`[{bar}]` {pct:.1f}%\n"
                    f"📦 {current/(1024*1024):.1f} / {file_size_mb:.1f} MB  •  ⚡ {speed_str}\n"
                    f"⏳ ETA: {eta_str}",
                    reply_markup=build_cancel_keyboard()
                )
            except Exception:
                pass

        playlist_name = meta.get("playlist", meta.get("album", "Merged"))
        artist        = meta.get("artist", "")
        caption       = f"🔀 **{ep_range} ⛥ {playlist_name}** ({len(downloaded_files)} episodes)\n"
        if artist:
            caption += f"👤 {artist}\n"
        caption += f"📊 {merge_type.upper()} • {len(downloaded_files)} eps • {file_size_mb:.1f} MB"

        try:
            # ffprobe merged file for duration/dimensions
            vid_duration = vid_width = vid_height = 0
            try:
                probe = await asyncio.create_subprocess_exec(
                    "ffprobe", "-v", "quiet", "-print_format", "json",
                    "-show_streams", "-show_format", output_file,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                )
                probe_out, _ = await probe.communicate()
                probe_data   = _json.loads(probe_out.decode())
                if probe_data.get("format", {}).get("duration"):
                    vid_duration = int(float(probe_data["format"]["duration"]))
                for stream in probe_data.get("streams", []):
                    if stream.get("codec_type") == "video":
                        vid_width  = stream.get("width", 0)
                        vid_height = stream.get("height", 0)
                        break
            except Exception:
                pass

            if merge_type == "mp3":
                performer_str = f"{artist} ⛥ @PFMXBOT" if artist else "@PFMXBOT"
                await client.send_audio(
                    chat_id=chat_id,
                    audio=output_file,
                    caption=caption,
                    title=tg_title,
                    performer=performer_str,
                    duration=vid_duration,
                    thumb=cover_path,
                    progress=merge_upload_progress,
                )
            else:
                await client.send_video(
                    chat_id=chat_id,
                    video=output_file,
                    caption=caption,
                    supports_streaming=True,
                    duration=vid_duration,
                    thumb=cover_path,
                    width=vid_width or None,
                    height=vid_height or None,
                    progress=merge_upload_progress,
                )

            await status_msg.edit_text(
                f"✅ Merge complete!\n"
                f"🔀 {len(downloaded_files)} episodes → {file_size_mb:.1f} MB {merge_type.upper()}\n"
                f"📚 Chapter markers embedded",
                reply_markup=None
            )

        except Exception as e:
            await status_msg.edit_text(f"❌ Upload failed: `{str(e)}`", reply_markup=None)

        finally:
            cancel_events.pop(user_id, None)
