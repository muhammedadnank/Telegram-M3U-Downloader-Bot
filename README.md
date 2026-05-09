<h1 align="center">🎵 Telegram M3U & JSON Downloader Bot</h1>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-blue.svg?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Framework-Pyrogram-blueviolet.svg?logo=telegram" alt="Pyrogram">
  <img src="https://img.shields.io/badge/Database-MongoDB-green.svg?logo=mongodb" alt="MongoDB">
  <img src="https://img.shields.io/badge/FFmpeg-Supported-orange.svg?logo=ffmpeg" alt="FFmpeg">
  <img src="https://img.shields.io/badge/yt--dlp-Integration-red.svg" alt="yt-dlp">
</p>

<p align="center">
  <b>A powerful Telegram bot built with Pyrogram (Kurigram fork) to download, process, and merge M3U playlists and JSON metadata files seamlessly.</b><br>
  <i>Features real-time progress tracking, per-user queuing, FFmpeg-powered merging, and rich metadata extraction.</i>
</p>

---

## ✨ Key Features

- 📄 **M3U & JSON Support** — Parse `.m3u` playlist files or structured `.json` metadata (e.g., KukuFM exports) with cover art, artist, description, and episode lists.
- 🎵 **Smart Media Processing** — Auto-detects MP3/MP4 formats from URLs with manual overrides.
- ⚙️ **Quality Selection** — Choose between Best, 960p, or 640p for video downloads.
- 📊 **Real-Time Progress** — Live download & upload progress bars with speed, ETA, and elapsed time.
- 🚦 **Per-User Queue System** — Concurrency limit of up to 3 downloads across all users; processes user jobs sequentially.
- 🛑 **Cancel Anytime** — Inline Cancel button available during both download and upload phases.
- 🔀 **Advanced Merge Engine** — Select specific episodes from a playlist and merge them into a single MP3/MP4 file with embedded chapter markers.
- 🎬 **AV Merge** — Automatically downloads video-only and audio-only streams and muxes them together.
- 🏷️ **Rich Metadata Tagging** — Embeds Title, Artist, Album, and Cover Art automatically via FFmpeg. Includes auto-formatting like `Episode ⛥ Show ⛥ @PFMXBOT`.
- ✏️ **Custom Filenames** — Template system using variables like `{title}`, `{artist}`, `{album}`, `{n}`.
- 📜 **Download History** — Stores the last 10 downloads per user in MongoDB.
- 📢 **Channel Auto-Post** — Optionally forward every completed file to a dedicated log/archive channel.
- 💾 **Persistent Settings** — Saves user-specific preferences (format, quality, filename template) in MongoDB.

---

## 🗂️ Project Structure

```text
Telegram M3U Downloader Bot/
├── src/
│   ├── bot.py              # Application Entry Point
│   ├── config.py           # Environment Variables & Configuration
│   ├── state.py            # Runtime State (Queues, Cancel Events)
│   ├── database.py         # MongoDB Helpers (motor)
│   ├── engine.py           # Core Download & Merge Engine
│   ├── utils.py            # M3U Parser, Keyboards, Helpers
│   └── plugins/
│       ├── commands.py     # /start, /history, /cancel, /queue, /settings, /merge
│       ├── callbacks.py    # Inline Button Handlers
│       └── document.py     # .m3u & .json File Handler
├── Dockerfile              # Docker container configuration
├── requirements.txt        # Python dependencies
└── .env                    # Environment variables (Do not commit)
```

---

## 🛠️ Prerequisites

Before you begin, ensure you have met the following requirements:
- **Python 3.11+** installed.
- **FFmpeg** and **yt-dlp** installed on your system.
- **Telegram API ID & Hash** from [my.telegram.org](https://my.telegram.org).
- **Telegram Bot Token** from [@BotFather](https://t.me/BotFather).
- **MongoDB Atlas URI** (The free tier works perfectly).

---

## 🚀 Local Setup & Installation

### 1. Clone the Repository
```bash
git clone https://github.com/muhammedadnank/Telegram-M3U-Downloader-Bot.git
cd Telegram-M3U-Downloader-Bot
```

### 2. Create a Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows use: venv\Scripts\activate
```

### 3. Install Python Dependencies
```bash
pip install -r requirements.txt
```

### 4. Install System Tools (FFmpeg & yt-dlp)

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install ffmpeg
sudo curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o /usr/local/bin/yt-dlp
sudo chmod a+rx /usr/local/bin/yt-dlp
```

**macOS:**
```bash
brew install ffmpeg yt-dlp
```

### 5. Configure Environment Variables
Copy `.env.example` to `.env` (or create a new `.env` file) and fill in your values:
```ini
API_ID=your_api_id
API_HASH=your_api_hash
BOT_TOKEN=your_bot_token
MONGO_URI=your_mongodb_uri

# Optional: ID of the channel to auto-post completed files (e.g., -1001234567890)
POST_CHANNEL=
```

### 6. Run the Bot
```bash
cd src
python bot.py
```

---

## 💬 Bot Commands

| Command | Description |
| :--- | :--- |
| `/start` | Show the welcome message and bot info |
| `/settings` | Customize format, quality, filename template, and channel posting |
| `/queue` | View your pending download queue |
| `/cancel` | Cancel an active or queued download |
| `/history` | View your 10 most recent downloads |
| `/merge` | Open merge mode for the currently active playlist |

---

## 📖 How It Works

1. **Upload File:** Send a `.m3u` or `.json` file to the bot.
2. **Parsing:** The bot parses episodes, extracts metadata, and displays the episode list with durations and auto-detected formats.
3. **Download Options:** 
   - Tap an episode to select its format (Auto / MP3 / MP4) and quality.
   - Tap **⬇️ All** to queue every episode sequentially.
   - Tap **🔀 Merge Episodes** to select specific episodes and merge them into one file with chapter markers.
4. **Processing:** The bot downloads streams via `yt-dlp`, embeds rich metadata (titles, artist, cover art) via `FFmpeg`, and uploads back to Telegram with a live progress bar.

---

## ☁️ Deployment Guides

### 🐳 Docker (Recommended)
Deploying with Docker is the easiest way to ensure all system dependencies (like FFmpeg) are correctly set up.
```bash
docker build -t m3u-bot .
docker run -d --name m3u-bot --env-file .env m3u-bot
```

### 🚀 Koyeb
1. Push your repository to GitHub.
2. Create a **New Service** → select **GitHub** → select this repo.
3. Set the Builder to **Dockerfile**.
4. Add the required environment variables: `API_ID`, `API_HASH`, `BOT_TOKEN`, `MONGO_URI`.
5. Click **Deploy**.

### 🏗️ Render
1. Create a **New Background Worker**.
2. Connect your GitHub repository.
3. Set Runtime to **Docker**.
4. Add the required environment variables: `API_ID`, `API_HASH`, `BOT_TOKEN`, `MONGO_URI`.
5. Click **Create Background Worker**.

> ⚠️ **Security Warning:** Never set environment variables directly in `config.py` or commit your `.env` file to version control.

---

## 🛡️ License & Disclaimer

This project is for personal use only. Please ensure you have the necessary rights to download and distribute any content you process using this bot.