# 🎵 Telegram M3U Downloader Bot

A powerful Telegram bot built with [Pyrogram](https://docs.pyrogram.org/) (Kurigram fork) to download, process, and merge M3U playlists and JSON metadata files — with real-time progress, per-user queuing, and FFmpeg-powered merging.

---

## ✨ Features

- **M3U & JSON support** — Parse `.m3u` playlist files or structured `.json` metadata (e.g. KukuFM exports) with cover art, artist, description, and episode list
- **MP3 / MP4 download** — Format auto-detected from URL; manual override available
- **Quality selection** — Best, 960p, 640p (video)
- **Real-time progress** — Live download + upload progress bars with speed, ETA, and elapsed time
- **Per-user queue** — Up to 3 concurrent downloads across all users; each user's jobs run in order
- **Cancel anytime** — Inline Cancel button during download and upload phases
- **Merge engine** — Select any episodes from a playlist and merge into a single MP3/MP4 with embedded chapter markers
- **AV merge** — Download video-only + audio-only streams and mux them together
- **Metadata tagging** — Title, artist, album, cover art embedded via FFmpeg
- **Custom filenames** — Template system using `{title}`, `{artist}`, `{album}`, `{n}`
- **Download history** — Last 10 downloads per user stored in MongoDB
- **Channel auto-post** — Optionally forward every completed file to a channel
- **Persistent settings** — Per-user format, quality, filename template saved in MongoDB

---

## 🗂️ Project Structure

```
Telegram M3U Downloader Bot/
├── src/
│   ├── bot.py              # Entry point
│   ├── config.py           # Env var loading
│   ├── state.py            # Runtime state (queues, cancel events)
│   ├── database.py         # MongoDB helpers (motor)
│   ├── engine.py           # Download + merge engine
│   ├── utils.py            # M3U parser, keyboards, helpers
│   └── plugins/
│       ├── commands.py     # /start /history /cancel /queue /settings /merge
│       ├── callbacks.py    # Inline button handlers
│       └── document.py     # .m3u / .json file handler
├── Dockerfile
├── requirements.txt
└── .env                    # Your credentials (never commit this)
```

---

## 🛠️ Requirements

- Python 3.11+
- FFmpeg + yt-dlp installed on the system
- Telegram API ID & API Hash — from [my.telegram.org](https://my.telegram.org)
- Telegram Bot Token — from [@BotFather](https://t.me/BotFather)
- MongoDB Atlas URI (free tier works)

---

## 🚀 Local Setup

**1. Clone the repo**
```bash
git clone <your-repo-url>
cd "Telegram M3U Downloader Bot"
```

**2. Create virtual environment**
```bash
python3 -m venv venv
source venv/bin/activate
```

**3. Install dependencies**
```bash
pip install -r requirements.txt
```

**4. Install system tools**

Ubuntu/Debian:
```bash
sudo apt install ffmpeg
sudo curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp \
  -o /usr/local/bin/yt-dlp && sudo chmod a+rx /usr/local/bin/yt-dlp
```

macOS:
```bash
brew install ffmpeg yt-dlp
```

**5. Configure credentials**

Copy `.env` and fill in your values:
```ini
API_ID=your_api_id
API_HASH=your_api_hash
BOT_TOKEN=your_bot_token
MONGO_URI=your_mongodb_uri

# Optional: auto-post completed files to a channel
POST_CHANNEL=
```

**6. Run**
```bash
cd src
python bot.py
```

---

## 💬 Bot Commands

| Command | Description |
|---|---|
| `/start` | Welcome message |
| `/settings` | Change format, quality, filename template, channel post |
| `/queue` | View pending downloads |
| `/cancel` | Cancel active download |
| `/history` | Last 10 downloads |
| `/merge` | Open merge mode for the current playlist |

---

## 📖 How It Works

1. Send a `.m3u` or `.json` file to the bot
2. Bot parses episodes and metadata; shows episode list with duration and auto-detected format
3. Tap an episode → choose format (Auto / MP3 / MP4) → choose quality
4. Or tap **⬇️ All** to queue every episode at once
5. Or tap **🔀 Merge Episodes** to select episodes and merge into one file with chapter markers
6. Bot downloads via `yt-dlp`, tags metadata with FFmpeg, uploads with live progress

---

## ☁️ Deployment

### Docker (recommended)

```bash
docker build -t m3u-bot .
docker run -d --env-file .env m3u-bot
```

### Koyeb

1. Push repo to GitHub
2. New Service → **GitHub** → select repo
3. Builder: **Dockerfile**
4. Add env vars: `API_ID`, `API_HASH`, `BOT_TOKEN`, `MONGO_URI`
5. Deploy

### Render

1. New → **Background Worker**
2. Connect GitHub repo
3. Runtime: **Docker**
4. Add env vars: `API_ID`, `API_HASH`, `BOT_TOKEN`, `MONGO_URI`
5. Create Background Worker

> ⚠️ Never set env vars directly in `config.py` or commit your `.env` file.

---

## 🛡️ License

For personal use. Ensure you have the rights to download and distribute any content you process.